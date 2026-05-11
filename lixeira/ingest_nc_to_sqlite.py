from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional, Tuple

import xarray as xr

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import db_sqlite
from src.processor import extract_points_from_lcfa

log = logging.getLogger("ingest_sqlite")


def find_event_points(ds: xr.Dataset):
    lat_vars = [v for v in ds.variables if "lat" in v.lower()]
    lon_vars = [v for v in ds.variables if "lon" in v.lower()]
    if not lat_vars or not lon_vars:
        return []
    lat = ds[lat_vars[0]].values
    lon = ds[lon_vars[0]].values
    events = []
    try:
        if getattr(lat, "ndim", 1) == 1 and getattr(lon, "ndim", 1) == 1 and len(lat) == len(lon):
            for i in range(len(lat)):
                events.append({"latitude": float(lat[i]), "longitude": float(lon[i])})
    except Exception:
        pass
    return events


def ingest(path: Path, sqlite_path: Path, bbox: Optional[Tuple[float, float, float, float]] = None):
    db_sqlite.create_schema(sqlite_path)
    raw_bytes = path.read_bytes()
    raw_id = db_sqlite.store_raw_file_sqlite(
        sqlite_path,
        source_url=None,
        source_time=None,
        file_format=path.suffix.lstrip('.'),
        blob=raw_bytes,
        metadata={"filename": path.name},
        bbox=bbox,
    )
    log.info("stored raw id=%s", raw_id)

    try:
        flashes = extract_points_from_lcfa(path, kind="flash").df
        events = extract_points_from_lcfa(path, kind="event").df

        flash_rows = [
            {"kind": "flash", "event_time": row["time"], "latitude": row["lat"], "longitude": row["lon"]}
            for _, row in flashes.iterrows()
        ]
        event_rows = [
            {"kind": "event", "event_time": row["time"], "latitude": row["lat"], "longitude": row["lon"]}
            for _, row in events.iterrows()
        ]

        n1 = db_sqlite.insert_events_sqlite(sqlite_path, flash_rows, raw_file_id=raw_id)
        n2 = db_sqlite.insert_events_sqlite(sqlite_path, event_rows, raw_file_id=raw_id)
        log.info("inserted flashes=%d events=%d", n1, n2)
    except Exception as ex:
        log.warning("GLM parse failed: %s", ex)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("file")
    parser.add_argument("--sqlite", default="webapp/backend/db/lightning.sqlite")
    parser.add_argument("--bbox")
    args = parser.parse_args(argv)
    bbox = None
    if args.bbox:
        parts = [float(p) for p in args.bbox.split(",")]
        if len(parts) == 4:
            bbox = (parts[0], parts[1], parts[2], parts[3])
    logging.basicConfig(level=logging.INFO)
    ingest(Path(args.file), Path(args.sqlite), bbox=bbox)


if __name__ == "__main__":
    raise SystemExit(main())
