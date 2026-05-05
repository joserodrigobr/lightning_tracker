from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re

import boto3
from botocore import UNSIGNED
from botocore.client import Config


@dataclass(frozen=True)
class DownloadResult:
    downloaded: list[Path]
    skipped_existing: int
    not_found: int


def _day_of_year(dt_utc: datetime) -> int:
    return int(dt_utc.strftime("%j"))


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _floor_to_interval(dt_utc: datetime, interval_seconds: int) -> datetime:
    dt_utc = _utc(dt_utc).replace(microsecond=0)
    ts = int(dt_utc.timestamp())
    floored = ts - (ts % int(interval_seconds))
    return datetime.fromtimestamp(floored, tz=timezone.utc)


def _ceil_to_interval(dt_utc: datetime, interval_seconds: int) -> datetime:
    dt_utc = _utc(dt_utc).replace(microsecond=0)
    ts = int(dt_utc.timestamp())
    interval = int(interval_seconds)
    rem = ts % interval
    if rem == 0:
        return dt_utc
    return datetime.fromtimestamp(ts + (interval - rem), tz=timezone.utc)


class GLMDownloader:
    def __init__(self, *, bucket: str, product_prefix: str, goes_number: int = 19):
        self.bucket = bucket
        self.product_prefix = product_prefix
        self.goes_number = goes_number
        self.s3 = boto3.client("s3", config=Config(signature_version=UNSIGNED))

        # Cache per hour prefix -> {stamp: key}
        self._hour_index: dict[str, dict[str, str]] = {}
        self._stamp_re = re.compile(r"_s(\d{14})_")

    def _prefix_for_hour(self, dt_utc: datetime) -> str:
        doy = _day_of_year(dt_utc)
        return f"{self.product_prefix}/{dt_utc.year}/{doy:03d}/{dt_utc.hour:02d}/"

    def _find_key(self, dt_utc: datetime) -> str | None:
        prefix = self._prefix_for_hour(dt_utc)
        # GOES filename stamp uses year + day-of-year (Julian day):
        #   _sYYYYJJJHHMMSSs_  ("s" = tenths of a second)
        # Our timestamps are aligned to full seconds, so tenths is always '0'.
        stamp = dt_utc.strftime("%Y%j%H%M%S") + "0"
        index = self._hour_index.get(prefix)
        if index is None:
            index = {}
            paginator = self.s3.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                for obj in page.get("Contents", []) or []:
                    key = obj.get("Key", "")
                    if not key.endswith(".nc"):
                        continue
                    m = self._stamp_re.search(key)
                    if not m:
                        continue
                    index[m.group(1)] = key
            self._hour_index[prefix] = index

        return index.get(stamp)

    def download_one(self, dt_utc: datetime, dest_dir: Path) -> Path | None:
        dest_dir.mkdir(parents=True, exist_ok=True)
        key = self._find_key(dt_utc)
        if not key:
            return None

        filename = key.split("/")[-1]
        dest_path = dest_dir / filename
        if dest_path.exists() and dest_path.stat().st_size > 0:
            return dest_path

        self.s3.download_file(self.bucket, key, str(dest_path))
        return dest_path

    def download_range(self, start_utc: datetime, end_utc: datetime, *, interval_seconds: int,
                       dest_root: Path) -> DownloadResult:
        start = _floor_to_interval(start_utc, interval_seconds)
        end = _ceil_to_interval(end_utc, interval_seconds)
        downloaded: list[Path] = []
        skipped_existing = 0
        not_found = 0

        t = start
        while t <= end:
            dest_dir = dest_root / t.strftime("%Y-%m-%d") / f"{t:%H}"
            try:
                path = self.download_one(t, dest_dir)
                if path is None:
                    not_found += 1
                else:
                    downloaded.append(path)
            except Exception:
                # treat as not_found for operational continuity
                not_found += 1
            t += timedelta(seconds=interval_seconds)

        return DownloadResult(downloaded=downloaded, skipped_existing=skipped_existing, not_found=not_found)
