from __future__ import annotations

import argparse
import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .config import load_settings
from .downloader import GLMDownloader
from .geo import haversine_km
from .processor import extract_points_from_lcfa


@dataclass(frozen=True)
class ActiveTakerSelection:
    takerId: int
    takerName: str
    flashesCount: int
    windowStartUtc: str
    windowEndUtc: str


def _utc_now_minus_lag(settings) -> datetime:
    return datetime.now(timezone.utc) - timedelta(seconds=int(settings.aws_availability_lag_sec))


def _load_takers(db_path: Path) -> list[dict[str, object]]:
    if not db_path.exists():
        return []

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "select id, nome_plataforma, latitude, longitude from tomadores_servico order by nome_plataforma"
        ).fetchall()

    return [
        {
            "id": int(row[0]),
            "name": str(row[1]),
            "lat": float(row[2]),
            "lon": float(row[3]),
        }
        for row in rows
    ]


def _load_flashes(settings, start_utc: datetime, end_utc: datetime) -> pd.DataFrame:
    downloader = GLMDownloader(bucket=settings.aws_bucket, product_prefix=settings.aws_product_prefix, goes_number=19)
    result: dict[str, object] = {"value": None, "error": None}

    def _worker() -> None:
        try:
            result["value"] = downloader.download_range(
                start_utc,
                end_utc,
                interval_seconds=settings.aws_interval_seconds,
                dest_root=settings.raw_dir,
            )
        except Exception as exc:
            result["error"] = exc

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    thread.join(timeout=max(1, int(settings.fetch_timeout_seconds)))
    if thread.is_alive() or result["error"] is not None:
        return pd.DataFrame(columns=["time", "lat", "lon"])

    dl = result["value"]
    if dl is None:
        return pd.DataFrame(columns=["time", "lat", "lon"])

    flashes = []
    for path in dl.downloaded:
        try:
            flashes.append(extract_points_from_lcfa(path, kind="flash").df)
        except Exception:
            continue

    if not flashes:
        return pd.DataFrame(columns=["time", "lat", "lon"])

    return pd.concat(flashes, ignore_index=True)


def select_active_taker(*, settings_path: Path, db_path: Path, window_minutes: int) -> ActiveTakerSelection:
    settings = load_settings(settings_path)
    takers = _load_takers(db_path)
    if not takers:
        raise RuntimeError(f"Nenhum tomador encontrado em {db_path}")

    now_utc = _utc_now_minus_lag(settings)
    start_utc = now_utc - timedelta(minutes=max(1, int(window_minutes)))

    flashes_df = _load_flashes(settings, start_utc, now_utc)
    if flashes_df.empty:
        first = takers[0]
        return ActiveTakerSelection(
            takerId=int(first["id"]),
            takerName=str(first["name"]),
            flashesCount=0,
            windowStartUtc=start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            windowEndUtc=now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )

    max_radius_km = float(max(settings.radii_km))
    flash_lat = flashes_df["lat"].to_numpy()
    flash_lon = flashes_df["lon"].to_numpy()

    best: tuple[int, str, int] | None = None
    for taker in takers:
        dist = haversine_km(float(taker["lat"]), float(taker["lon"]), flash_lat, flash_lon)
        count = int(np.count_nonzero(dist <= max_radius_km))
        candidate = (int(taker["id"]), str(taker["name"]), count)
        if best is None or candidate[2] > best[2] or (candidate[2] == best[2] and candidate[0] < best[0]):
            best = candidate

    assert best is not None
    return ActiveTakerSelection(
        takerId=best[0],
        takerName=best[1],
        flashesCount=best[2],
        windowStartUtc=start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        windowEndUtc=now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Select the active taker for the last time window.")
    parser.add_argument("--settings", default="config/settings.yaml")
    parser.add_argument("--db-path", required=True)
    parser.add_argument("--window-minutes", type=int, default=30)
    args = parser.parse_args()

    result = select_active_taker(
        settings_path=Path(args.settings),
        db_path=Path(args.db_path),
        window_minutes=int(args.window_minutes),
    )
    print(json.dumps(result.__dict__, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
