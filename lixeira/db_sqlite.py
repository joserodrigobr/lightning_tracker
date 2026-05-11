from __future__ import annotations

import json
import gzip
import hashlib
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple


def _compute_checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _normalize_event_time(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if isinstance(value, str):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def create_schema(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.executescript(
            """
            create table if not exists raw_files (
                id integer primary key autoincrement,
                source_url text,
                source_time text,
                downloaded_at text default current_timestamp,
                file_format text,
                checksum text,
                uncompressed_size integer,
                compressed_size integer,
                min_lat real,
                min_lon real,
                max_lat real,
                max_lon real,
                compressed_blob blob,
                metadata text,
                created_at text default current_timestamp,
                unique(source_url, source_time)
            );

            create table if not exists lightning_events (
                id integer primary key autoincrement,
                raw_file_id integer,
                kind text not null default 'flash',
                event_time text,
                latitude real,
                longitude real,
                intensity real,
                attributes text,
                created_at text default current_timestamp
            );

            create table if not exists daily_tables (
                id integer primary key autoincrement,
                taker_id integer not null,
                taker_name text,
                date text not null,
                generated_at text default current_timestamp,
                csv_blob blob,
                csv_text text,
                metadata text,
                filesize integer,
                unique(taker_id, date)
            );
            """
        )
        conn.commit()


def store_raw_file_sqlite(
    db_path: Path,
    *,
    source_url: Optional[str],
    source_time: Optional[str],
    file_format: Optional[str],
    blob: bytes,
    metadata: Optional[Dict[str, Any]] = None,
    bbox: Optional[Tuple[float, float, float, float]] = None,
) -> int:
    compressed = gzip.compress(blob)
    checksum = _compute_checksum(compressed)
    uncompressed_size = len(blob)
    compressed_size = len(compressed)

    min_lon = min_lat = max_lon = max_lat = None
    if bbox:
        min_lon, min_lat, max_lon, max_lat = bbox

    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            insert into raw_files
              (source_url, source_time, file_format, checksum, uncompressed_size, compressed_size,
               min_lat, min_lon, max_lat, max_lon, compressed_blob, metadata)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                source_url,
                source_time,
                file_format,
                checksum,
                uncompressed_size,
                compressed_size,
                min_lat,
                min_lon,
                max_lat,
                max_lon,
                sqlite3.Binary(compressed),
                json.dumps(metadata or {}),
            ),
        )
        raw_id = cur.lastrowid
        conn.commit()
    return raw_id


def insert_events_sqlite(db_path: Path, events: Iterable[Dict[str, Any]], raw_file_id: Optional[int] = None) -> int:
    rows = []
    for ev in events:
        rows.append((raw_file_id, str(ev.get("kind") or "flash").lower().strip(), _normalize_event_time(ev.get("event_time")), float(ev["latitude"]), float(ev["longitude"]), ev.get("intensity"), json.dumps({k: v for k, v in ev.items() if k not in ("latitude", "longitude", "event_time", "intensity", "kind")})))

    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.executemany(
            """
            insert into lightning_events (raw_file_id, kind, event_time, latitude, longitude, intensity, attributes)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        n = cur.rowcount if cur.rowcount is not None else len(rows)
        conn.commit()
    return n
