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
from .data_store import get_postgres_dsn, load_points_from_postgres, store_daily_table_in_postgres
from .config import load_settings
from .core import _radii_labels, _slug, compute_table_4x5min, _5min_time_labels_for_date
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
    dsn = get_postgres_dsn()
    if dsn:
        try:
            db_df = load_points_from_postgres(dsn=dsn, kind="flash", start_utc=start_utc, end_utc=end_utc)
            if not db_df.empty:
                return db_df
        except Exception:
            pass

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


def build_custom_table(flashes_df: pd.DataFrame, lat0: float, lon0: float, radii_km: list[float], start_local: datetime, end_local: datetime) -> tuple[np.ndarray, list[str]]:
    total_minutes = int((end_local - start_local).total_seconds() / 60)
    num_bins = total_minutes // 5
    if num_bins <= 0:
        return np.zeros((4, 0), dtype=np.int64), []
        
    table = np.zeros((4, num_bins), dtype=np.int64)
    labels = [(start_local + timedelta(minutes=5 * i)).strftime("%H:%M") for i in range(num_bins)]
    
    if flashes_df.empty:
        return table, labels
        
    from .core import haversine_km, ring_index
    df = flashes_df.copy()
    tloc = df["time"].dt.tz_convert(start_local.tzinfo)
    mask = (tloc >= start_local) & (tloc < end_local)
    df = df[mask].copy()
    if df.empty:
        return table, labels
        
    dist = haversine_km(lat0, lon0, df["lat"].to_numpy(), df["lon"].to_numpy())
    r_idx = ring_index(dist, radii_km)
    within = r_idx < len(radii_km)
    df = df[within].copy()
    if df.empty:
        return table, labels
    df["ring"] = r_idx[within]
    
    delta_min = (df["time"].dt.tz_convert(start_local.tzinfo) - start_local).dt.total_seconds() / 60
    bin_idx = (delta_min // 5).astype(int)
    df["bin"] = bin_idx
    valid_bins = (df["bin"] >= 0) & (df["bin"] < num_bins)
    df = df[valid_bins]
    
    for ring in range(4):
        sub = df[df["ring"] == ring]
        counts = sub.groupby("bin").size()
        for b, count in counts.items():
            table[ring, b] = count
            
    return table, labels

def build_table_result(*, settings_path: Path, taker_id: int, taker_name: str, lat0: float, lon0: float, end_local: datetime, period: str) -> TableGenerationResult:
    settings = load_settings(settings_path)

    if period == "yesterday":
        local_midnight_today = end_local.replace(hour=0, minute=0, second=0, microsecond=0)
        start_local = local_midnight_today - timedelta(days=1)
        end_local_period = local_midnight_today
    elif period == "3h":
        start_local = end_local - timedelta(hours=3)
        end_local_period = end_local
    else:
        # Default full day for the given date
        start_local = end_local.replace(hour=0, minute=0, second=0, microsecond=0)
        end_local_period = start_local + timedelta(days=1)

    start_utc = _to_utc(start_local)
    lag = timedelta(seconds=int(settings.aws_availability_lag_sec))
    end_utc = min(_to_utc(end_local_period), datetime.now(timezone.utc) - lag)

    flashes_df = _download_flashes(settings, start_utc, end_utc)
    table_4x5min, hour_labels = build_custom_table(flashes_df, lat0, lon0, settings.radii_km, start_local, end_local_period)

    radii_labels = _radii_labels(settings.radii_km)

    archiver = HourlyArchiver(
        enabled=True,
        screenshots_root=settings.archive_screenshots_dir,
        tables_root=settings.archive_tables_dir,
        save_on_hour_change=False,
    )
    taker_slug = _slug(taker_name)
    csv_path = archiver.save_table_csv(
        table_4x5min,
        dt_local=end_local_period,
        taker_slug=taker_slug,
        hours_labels=hour_labels,
        radii_labels=radii_labels,
    )

    try:
        rel_path = str(csv_path.resolve().relative_to(settings.archive_tables_dir.resolve())).replace("\\", "/")
    except Exception:
        rel_path = csv_path.as_posix()

    dsn = get_postgres_dsn()
    if dsn:
        try:
            store_daily_table_in_postgres(
                dsn=dsn,
                taker_id=taker_id,
                taker_name=taker_name,
                date=end_local,
                csv_text=csv_path.read_text(encoding="utf-8"),
                metadata={
                    "savedAtLocal": end_local.strftime("%Y-%m-%d %H:%M:%S"),
                    "endLocal": end_local.strftime("%Y-%m-%d %H:%M:%S"),
                    "hourLabels": hour_labels,
                    "radiiLabels": radii_labels,
                },
            )
        except Exception:
            pass

    return TableGenerationResult(
        taker_name=taker_name,
        csv_path=str(csv_path),
        csv_relative_path=rel_path,
        saved_at_local=end_local.strftime("%Y-%m-%d %H:%M:%S"),
        end_local=end_local_period.strftime("%Y-%m-%d %H:%M:%S"),
        hour_labels=hour_labels,
        radii_labels=radii_labels,
        values_4x24=table_4x5min.astype(int).tolist(),
    )


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Generate and save 4x24 lightning table CSV")
    p.add_argument("--settings", default=str(Path("config/settings.yaml")), help="Path to settings.yaml")
    p.add_argument("--taker-id", required=False, default="0", help="Taker numeric id")
    p.add_argument("--name", required=True, help="Taker name")
    p.add_argument("--lat", required=True, type=float, help="Taker latitude")
    p.add_argument("--lon", required=True, type=float, help="Taker longitude")
    p.add_argument("--end-local", default="", help="End local (YYYY-MM-DDTHH:MM:SS) or empty")
    p.add_argument("--period", default="24h", help="Period (24h, yesterday, 3h)")
    return p


def main() -> int:
    args = _build_arg_parser().parse_args()

    tz = _local_tzinfo()
    now = datetime.now().astimezone(tz)
    end_local = _parse_local_dt(args.end_local, base=now)

    result = build_table_result(
        settings_path=Path(str(args.settings)),
        taker_id=int(args.taker_id),
        taker_name=str(args.name),
        lat0=float(args.lat),
        lon0=float(args.lon),
        end_local=end_local,
        period=args.period,
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
