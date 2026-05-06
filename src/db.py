from __future__ import annotations

import gzip
import json
import hashlib
from urllib.parse import urlparse, unquote
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

import pg8000.dbapi as pgdb


def get_conn(dsn: str):
    return pgdb.connect(**_dsn_kwargs(dsn))


def _dsn_kwargs(dsn: str) -> Dict[str, Any]:
    text = (dsn or "").strip()
    if not text:
        raise ValueError("DSN vazio")

    if "://" in text:
        parsed = urlparse(text)
        return {
            "host": parsed.hostname,
            "port": parsed.port,
            "database": parsed.path.lstrip("/") or None,
            "user": unquote(parsed.username) if parsed.username else None,
            "password": unquote(parsed.password) if parsed.password else None,
        }

    parts: Dict[str, Any] = {}
    for chunk in text.split():
        if "=" not in chunk:
            continue
        key, value = chunk.split("=", 1)
        parts[key.strip()] = value.strip()
    return {
        "host": parts.get("host"),
        "port": int(parts["port"]) if parts.get("port") else None,
        "database": parts.get("dbname") or parts.get("database"),
        "user": parts.get("user"),
        "password": parts.get("password"),
    }


def create_schema(conn, sql_path: Path) -> None:
    with sql_path.open("r", encoding="utf-8") as f:
        sql = f.read()
    cur = conn.cursor()
    try:
        cur.execute(sql)
    finally:
        cur.close()
    conn.commit()


def _compute_checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _normalize_event_time(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "to_pydatetime"):
        return value.to_pydatetime()
    return value


def store_raw_file(
    conn,
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
    geom_wkt = None
    if bbox:
        min_lon, min_lat, max_lon, max_lat = bbox
        geom_wkt = f"SRID=4326;POLYGON(({min_lon} {min_lat},{min_lon} {max_lat},{max_lon} {max_lat},{max_lon} {min_lat},{min_lon} {min_lat}))"

    cur = conn.cursor()
    try:
        cur.execute(
            """
            insert into raw_files
              (source_url, source_time, file_format, checksum, uncompressed_size, compressed_size,
               bbox, min_lat, min_lon, max_lat, max_lon, compressed_blob, metadata)
            values (%s, %s, %s, %s, %s, %s,
                    ST_GeomFromText(%s,4326), %s, %s, %s, %s, %s, %s)
            returning id
        """,
            (
                source_url,
                source_time,
                file_format,
                checksum,
                uncompressed_size,
                compressed_size,
                geom_wkt,
                min_lat,
                min_lon,
                max_lat,
                max_lon,
                compressed,
                json.dumps(metadata or {}),
            ),
        )
        raw_id = cur.fetchone()[0]
    finally:
        cur.close()
    conn.commit()
    return raw_id


def insert_events(conn, events: Iterable[Dict[str, Any]], raw_file_id: Optional[int] = None) -> int:
    rows = []
    for ev in events:
        lat = float(ev["latitude"])
        lon = float(ev["longitude"])
        event_time = _normalize_event_time(ev.get("event_time"))
        intensity = ev.get("intensity")
        kind = str(ev.get("kind") or "flash").lower().strip()
        attributes = json.dumps({k: v for k, v in ev.items() if k not in ("latitude", "longitude", "event_time", "intensity")})
        rows.append((raw_file_id, kind, event_time, lon, lat, lat, lon, intensity, attributes))

    cur = conn.cursor()
    try:
        cur.executemany(
            """
            insert into lightning_events
              (raw_file_id, kind, event_time, geom, latitude, longitude, intensity, attributes)
            values (%s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s),4326), %s, %s, %s, %s)
        """,
            rows,
        )
    finally:
        cur.close()
    conn.commit()
    return len(rows)


def delete_raw_files_older_than(conn, cutoff_utc) -> int:
    """Delete raw file blobs older than the provided UTC cutoff."""
    cur = conn.cursor()
    try:
        cur.execute(
            """
            delete from raw_files
            where source_time is not null
              and source_time < %s
            """,
            (cutoff_utc,)
        )
        deleted = cur.rowcount or 0
    finally:
        cur.close()
    conn.commit()
    return deleted
