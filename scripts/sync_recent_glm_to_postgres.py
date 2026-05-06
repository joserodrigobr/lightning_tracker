#!/usr/bin/env python3
"""Keep the recent GLM window in PostgreSQL and purge expired raw blobs.

This script is intended to run periodically. It downloads the last few hours
of GLM files, stores raw NetCDF blobs in Postgres, inserts normalized events,
and deletes raw blobs older than the configured retention window.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src import db
from src.config import load_settings
from src.downloader import GLMDownloader
from src.data_store import get_postgres_dsn
from src.processor import extract_points_from_lcfa
from src.cleanup import FileCleanupManager
from src.fetch_tracker import FetchTracker


def setup_logging(level=logging.INFO):
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        level=level,
    )
    return logging.getLogger(__name__)


def _parse_source_time(filename: str) -> datetime | None:
    parts = filename.split("_")
    for part in parts:
        if not part.startswith("s"):
            continue
        stamp = part[1:14]
        if len(stamp) != 13:
            continue
        try:
            year = int(stamp[0:4])
            jday = int(stamp[4:7])
            hour = int(stamp[7:9])
            minute = int(stamp[9:11])
            second = int(stamp[11:13])
            jan1 = datetime(year, 1, 1, tzinfo=timezone.utc)
            dt = jan1 + timedelta(days=jday - 1)
            return dt.replace(hour=hour, minute=minute, second=second, microsecond=0)
        except Exception:
            return None
    return None


def _ingest_file(conn, nc_path: Path, logger, bucket: str) -> tuple[bool, int, int]:
    source_url = f"s3://{bucket}/GLM-L2-LCFA/{nc_path.name}"
    source_time = _parse_source_time(nc_path.name)
    if source_time is None:
        logger.warning("Skipping file without a parseable source time: %s", nc_path.name)
        return False, 0, 0

    cur = conn.cursor()
    try:
        cur.execute(
            "select id from raw_files where source_url = %s and source_time = %s",
            (source_url, source_time),
        )
        if cur.fetchone() is not None:
            return True, 0, 0
    finally:
        cur.close()

    flashes_points = extract_points_from_lcfa(str(nc_path), kind="flash")
    events_points = extract_points_from_lcfa(str(nc_path), kind="event")

    flashes_list: list[dict[str, object]] = []
    for _, row in flashes_points.df.iterrows():
        flashes_list.append({
            "latitude": row["lat"],
            "longitude": row["lon"],
            "event_time": row["time"].isoformat() if hasattr(row["time"], "isoformat") else str(row["time"]),
            "kind": "flash",
        })

    events_list: list[dict[str, object]] = []
    for _, row in events_points.df.iterrows():
        events_list.append({
            "latitude": row["lat"],
            "longitude": row["lon"],
            "event_time": row["time"].isoformat() if hasattr(row["time"], "isoformat") else str(row["time"]),
            "kind": "event",
        })

    with nc_path.open("rb") as f:
        blob = f.read()

    raw_id = db.store_raw_file(
        conn,
        source_url=source_url,
        source_time=source_time,
        file_format="NetCDF4",
        blob=blob,
        bbox=None,
    )

    if flashes_list:
        db.insert_events(conn, flashes_list, raw_file_id=raw_id)
    if events_list:
        db.insert_events(conn, events_list, raw_file_id=raw_id)

    return False, len(flashes_list), len(events_list)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync recent GLM files into PostgreSQL")
    parser.add_argument("--settings", default=str(Path("config/settings.yaml")), help="Path to settings.yaml")
    parser.add_argument("--retention-hours", type=int, default=3, help="How many hours of raw blobs to keep")
    parser.add_argument("--lookback-minutes", type=int, default=5, help="How many recent minutes to refresh")
    parser.add_argument("--lookback-hours", type=int, default=None, help="Deprecated. How many recent hours to refresh")
    parser.add_argument("--keep-raw-files", action="store_true", help="Do not delete raw .nc files after processing")
    args = parser.parse_args()

    logger = setup_logging()
    settings = load_settings(Path(args.settings))
    dsn_value = get_postgres_dsn()
    if not dsn_value:
        raise SystemExit("LIGHTNING_TRACKER_PG_DSN is not set")

    now_utc = datetime.now(timezone.utc)
    retention_cutoff = now_utc - timedelta(hours=max(1, args.retention_hours))

    # Determine start_utc using fetch tracker: initial window once, then incremental
    tracker = None
    if settings.enable_fetch_tracker:
        tracker = FetchTracker(settings.fetch_state_file)

    last_fetched = None
    if tracker:
        try:
            last_fetched = tracker.get_last_fetched(settings.aws_product_prefix, dsn_value)
        except Exception:
            last_fetched = None

    if args.lookback_hours is not None:
        lookback_minutes = max(1, args.lookback_hours) * 60
    else:
        lookback_minutes = max(1, args.lookback_minutes)

    if last_fetched is None:
        # First run: fetch initial window (combine configured initial and CLI lookback)
        initial_minutes = int(getattr(settings, "fetch_initial_minutes", 5))
        refresh_minutes = max(initial_minutes, lookback_minutes)
        start_utc = now_utc - timedelta(minutes=refresh_minutes)
    else:
        # Incremental: small overlap to be safe
        overlap = int(getattr(settings, "fetch_overlap_seconds", 10))
        start_utc = last_fetched - timedelta(seconds=overlap)

    downloader = GLMDownloader(
        bucket=settings.aws_bucket,
        product_prefix=settings.aws_product_prefix,
        goes_number=19,
    )
    result = downloader.download_range(
        start_utc,
        now_utc,
        interval_seconds=settings.aws_interval_seconds,
        dest_root=settings.raw_dir,
    )

    total_flashes = 0
    total_events = 0
    skipped = 0
    with db.get_conn(dsn_value) as conn:
        for path in result.downloaded:
            try:
                already, flashes_count, events_count = _ingest_file(conn, path, logger, settings.aws_bucket)
                if not already:
                    try:
                        st = _parse_source_time(path.name)
                        if st is None:
                            st = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
                        if tracker:
                            tracker.update_last_fetched(settings.aws_product_prefix, st)
                    except Exception:
                        logger.warning("Failed updating fetch tracker for %s", path.name)
                else:
                    skipped += 1
                total_flashes += flashes_count
                total_events += events_count
            except Exception as exc:
                logger.error("Failed to ingest %s: %s", path.name, exc)

        deleted = db.delete_raw_files_older_than(conn, retention_cutoff)

    logger.info(
        "Synced %d files (%d skipped, %d flashes, %d events) and deleted %d raw blobs older than %s",
        len(result.downloaded),
        skipped,
        total_flashes,
        total_events,
        deleted,
        retention_cutoff.isoformat(),
    )

    # Clean up raw .nc files if enabled
    if settings.cleanup_enabled and not args.keep_raw_files:
        cleanup_manager = FileCleanupManager(logger=logger)
        cleanup_hours = settings.cleanup_days_old * 24
        cleaned = cleanup_manager.cleanup_raw_files(settings.raw_dir, cleanup_hours)
        logger.info("Cleaned up %d raw .nc files older than %d days", cleaned, settings.cleanup_days_old)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())