from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import xarray as xr

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import db
from src.processor import extract_points_from_lcfa


log = logging.getLogger("ingest")


def find_event_points(ds: xr.Dataset) -> List[Dict[str, Any]]:
    # Heuristic event extraction: look for coordinate-like variables
    lat_vars = [v for v in ds.variables if "lat" in v.lower()]
    lon_vars = [v for v in ds.variables if "lon" in v.lower()]
    time_vars = [v for v in ds.variables if "time" in v.lower()]

    if not lat_vars or not lon_vars:
        return []

    lat = ds[lat_vars[0]].values
    lon = ds[lon_vars[0]].values

    events: List[Dict[str, Any]] = []
    # If 1D arrays of same length, map them
    try:
        if getattr(lat, "ndim", 1) == 1 and getattr(lon, "ndim", 1) == 1 and len(lat) == len(lon):
            for i in range(len(lat)):
                events.append({"latitude": float(lat[i]), "longitude": float(lon[i])})
    except Exception:
        pass

    return events


def ingest(path: Path, dsn: str, bbox: Optional[Tuple[float, float, float, float]] = None):
    conn = db.get_conn(dsn)
    try:
        # store raw blob and metadata
        raw_bytes = path.read_bytes()
        metadata = {"filename": path.name}
        raw_id = db.store_raw_file(
            conn,
            source_url=None,
            source_time=None,
            file_format=path.suffix.lstrip("."),
            blob=raw_bytes,
            metadata=metadata,
            bbox=bbox,
        )
        log.info("stored raw file id=%s", raw_id)

        # attempt to open with the real GLM parser and extract both flashes and events
        try:
            flashes = extract_points_from_lcfa(path, kind="flash").df
            events = extract_points_from_lcfa(path, kind="event").df

            flash_rows = []
            for _, row in flashes.iterrows():
                flash_rows.append({
                    "kind": "flash",
                    "event_time": row["time"].to_pydatetime() if hasattr(row["time"], "to_pydatetime") else row["time"],
                    "latitude": row["lat"],
                    "longitude": row["lon"],
                })

            event_rows = []
            for _, row in events.iterrows():
                event_rows.append({
                    "kind": "event",
                    "event_time": row["time"].to_pydatetime() if hasattr(row["time"], "to_pydatetime") else row["time"],
                    "latitude": row["lat"],
                    "longitude": row["lon"],
                })

            n1 = db.insert_events(conn, flash_rows, raw_file_id=raw_id) if flash_rows else 0
            n2 = db.insert_events(conn, event_rows, raw_file_id=raw_id) if event_rows else 0
            log.info("extracted flashes=%d events=%d", n1, n2)
        except Exception as ex:
            log.warning("xarray open/parse failed: %s", ex)
    finally:
        conn.close()


def main(argv: Optional[List[str]] = None):
    parser = argparse.ArgumentParser()
    parser.add_argument("file", help="Path to .nc file to ingest")
    parser.add_argument("--dsn", required=True, help="Postgres DSN (psycopg2)")
    parser.add_argument("--bbox", help="Optional bbox min_lon,min_lat,max_lon,max_lat")
    args = parser.parse_args(argv)

    bbox = None
    if args.bbox:
        parts = [float(p) for p in args.bbox.split(",")]
        if len(parts) == 4:
            bbox = (parts[0], parts[1], parts[2], parts[3])

    logging.basicConfig(level=logging.INFO)
    ingest(Path(args.file), args.dsn, bbox=bbox)


if __name__ == "__main__":
    raise SystemExit(main())
