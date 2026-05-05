from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

os.environ.setdefault("MPLBACKEND", "Agg")

from .archiver import HourlyArchiver
from .config import load_settings
from .core import _hour_labels, _radii_labels, _slug, compute_table_4x24
from .downloader import GLMDownloader
from .processor import extract_points_from_lcfa

_GLM_STAMP_RE = re.compile(r"_s(\d{14})_")


@dataclass(frozen=True)
class TableGenerationResult:
    taker_name: str
    csv_path: str
    csv_relative_path: str
    saved_at_local: str
    end_local: str
    hour_labels: list[str]
    radii_labels: list[str]
    values_4x24: list[list[int]]


def _local_tzinfo() -> timezone:
    return datetime.now().astimezone().tzinfo or timezone.utc


def _parse_local_dt(text: str | None, *, base: datetime) -> datetime:
    s = (text or "").strip()
    if not s:
        return base

    s2 = s.replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s2, fmt).replace(tzinfo=base.tzinfo)
        except ValueError:
            pass

    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            t = datetime.strptime(s, fmt).time()
            return base.replace(hour=t.hour, minute=t.minute, second=t.second, microsecond=0)
        except ValueError:
            pass

    raise ValueError("Formato inválido de data/hora")


def _to_utc(dt_local: datetime) -> datetime:
    if dt_local.tzinfo is None:
        return dt_local.replace(tzinfo=timezone.utc)
    return dt_local.astimezone(timezone.utc)


def _download_flashes(settings, start_utc: datetime, end_utc: datetime) -> pd.DataFrame:
    downloader = GLMDownloader(bucket=settings.aws_bucket, product_prefix=settings.aws_product_prefix, goes_number=19)
    result = downloader.download_range(start_utc, end_utc, interval_seconds=settings.aws_interval_seconds, dest_root=settings.raw_dir)

    flashes: list[pd.DataFrame] = []
    for path in result.downloaded:
        try:
            fdf = extract_points_from_lcfa(path, kind="flash").df
            if not fdf.empty:
                flashes.append(fdf)
        except Exception:
            continue

    if not flashes:
        return pd.DataFrame(columns=["time", "lat", "lon"])
    return pd.concat(flashes, ignore_index=True)


def build_table_result(*, settings_path: Path, taker_name: str, lat0: float, lon0: float, end_local: datetime) -> TableGenerationResult:
    settings = load_settings(settings_path)

    lag = timedelta(seconds=int(settings.aws_availability_lag_sec))
    end_utc = min(_to_utc(end_local), datetime.now(timezone.utc) - lag)
    start_utc = end_utc - timedelta(hours=24)

    flashes_df = _download_flashes(settings, start_utc, end_utc)
    table_4x24 = compute_table_4x24(flashes_df, lat0=lat0, lon0=lon0, radii_km=settings.radii_km, end_local=end_local)

    hour_labels = _hour_labels(end_local)
    radii_labels = _radii_labels(settings.radii_km)

    archiver = HourlyArchiver(
        enabled=True,
        screenshots_root=settings.archive_screenshots_dir,
        tables_root=settings.archive_tables_dir,
        save_on_hour_change=False,
    )
    taker_slug = _slug(taker_name)
    csv_path = archiver.save_table_csv(
        table_4x24,
        dt_local=end_local,
        taker_slug=taker_slug,
        hours_labels=hour_labels,
        radii_labels=radii_labels,
    )

    try:
        rel_path = str(csv_path.resolve().relative_to(settings.archive_tables_dir.resolve())).replace("\\", "/")
    except Exception:
        rel_path = csv_path.as_posix()

    return TableGenerationResult(
        taker_name=taker_name,
        csv_path=str(csv_path),
        csv_relative_path=rel_path,
        saved_at_local=end_local.strftime("%Y-%m-%d %H:%M:%S"),
        end_local=end_local.strftime("%Y-%m-%d %H:%M:%S"),
        hour_labels=hour_labels,
        radii_labels=radii_labels,
        values_4x24=table_4x24.astype(int).tolist(),
    )


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Generate and save 4x24 lightning table CSV")
    p.add_argument("--settings", default=str(Path("config/settings.yaml")), help="Path to settings.yaml")
    p.add_argument("--name", required=True, help="Taker name")
    p.add_argument("--lat", required=True, type=float, help="Taker latitude")
    p.add_argument("--lon", required=True, type=float, help="Taker longitude")
    p.add_argument("--end-local", default="", help="End local (YYYY-MM-DDTHH:MM:SS) or empty")
    return p


def main() -> int:
    args = _build_arg_parser().parse_args()

    tz = _local_tzinfo()
    now = datetime.now().astimezone(tz)
    end_local = _parse_local_dt(args.end_local, base=now)

    result = build_table_result(
        settings_path=Path(str(args.settings)),
        taker_name=str(args.name),
        lat0=float(args.lat),
        lon0=float(args.lon),
        end_local=end_local,
    )

    payload = {
        "takerName": result.taker_name,
        "csvPath": result.csv_path,
        "csvRelativePath": result.csv_relative_path,
        "savedAtLocal": result.saved_at_local,
        "endLocal": result.end_local,
        "hourLabels": result.hour_labels,
        "radiiLabels": result.radii_labels,
        "values4x24": result.values_4x24,
    }
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
