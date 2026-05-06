#!/usr/bin/env python3
"""
Batch ingest GLM files from disk into PostgreSQL.

Usage:
  python scripts/backfill_glm_to_postgres.py \\
    --dsn "host=127.0.0.1 port=6543 dbname=lightning user=user password=pass" \\
    --data-path "data/raw/glm_20s_goes" \\
    --limit 1000

This script:
1. Scans data/raw/glm_20s_goes/ recursively for .nc files
2. Checks which files are already in raw_files table
3. Ingests new files with flash/event extraction
4. Logs progress with counts and time estimates
"""

import sys
import argparse
import logging
from pathlib import Path
from datetime import datetime, timedelta
import time

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src import db, processor
from src.processor import extract_points_from_lcfa


def setup_logging(level=logging.INFO):
    """Configure logging with timestamps and level indicators."""
    logging.basicConfig(
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        level=level
    )
    return logging.getLogger(__name__)


def get_source_time_from_filename(filename: str) -> str:
    """
    Extract source time from GLM filename.
    Example: OR_GLM-L2-LCFA_G19_s20261241700000_e20261241700200_c20261241700212.nc
    Returns: 2026-05-04T02:59:59.000Z
    """
    try:
        # Parse start time: sYYYYJJJHHMMSSfff (YYYYJJJHHMMSS + milliseconds)
        parts = filename.split('_')
        for part in parts:
            if part.startswith('s'):
                # Extract sYYYYJJJHHMMSSfff
                time_str = part[1:14]  # YYYYJJJHHMMss
                if len(time_str) == 13:
                    year = int(time_str[0:4])
                    jday = int(time_str[4:7])
                    hour = int(time_str[7:9])
                    minute = int(time_str[9:11])
                    second = int(time_str[11:13])
                    
                    # Convert Julian day to date
                    jan1 = datetime(year, 1, 1)
                    target_date = jan1 + timedelta(days=jday - 1)
                    
                    dt = datetime(
                        target_date.year,
                        target_date.month,
                        target_date.day,
                        hour, minute, second
                    )
                    return dt.isoformat() + 'Z'
    except Exception as e:
        logging.warning(f"Could not parse timestamp from {filename}: {e}")
    
    return None


def file_already_ingested(conn, source_url: str, source_time: str) -> bool:
    """Check if file is already in raw_files table."""
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM raw_files WHERE source_url = %s AND source_time = %s",
            (source_url, source_time)
        )
        result = cur.fetchone()
        cur.close()
        return result is not None
    except Exception as e:
        logging.error(f"Error checking if file exists: {e}")
        return False


def ingest_file(conn, nc_path: Path, dsn: str, logger) -> dict:
    """
    Ingest a single GLM .nc file.
    
    Returns:
        dict with keys: success, flashes, events, raw_id, error
    """
    result = {
        'success': False,
        'flashes': 0,
        'events': 0,
        'raw_id': None,
        'error': None
    }
    
    try:
        source_url = f"s3://noaa-goes16/GLM-L2-LCFA/{nc_path.name}"
        source_time = get_source_time_from_filename(nc_path.name)
        
        if not source_time:
            result['error'] = "Could not extract source_time from filename"
            return result
        
        # Check if already ingested
        if file_already_ingested(conn, source_url, source_time):
            result['success'] = True
            result['error'] = "File already ingested (skipped)"
            return result
        
        # Extract flashes and events from .nc file
        logger.info(f"  Extracting data from {nc_path.name}...")
        flashes_points = extract_points_from_lcfa(str(nc_path), kind='flash')
        events_points = extract_points_from_lcfa(str(nc_path), kind='event')
        
        # Convert Points objects to list of dicts with required keys
        flashes_list = []
        for _, row in flashes_points.df.iterrows():
            flashes_list.append({
                'latitude': row['lat'],
                'longitude': row['lon'],
                'event_time': row['time'].isoformat() if hasattr(row['time'], 'isoformat') else str(row['time']),
                'kind': 'flash'
            })
        
        events_list = []
        for _, row in events_points.df.iterrows():
            events_list.append({
                'latitude': row['lat'],
                'longitude': row['lon'],
                'event_time': row['time'].isoformat() if hasattr(row['time'], 'isoformat') else str(row['time']),
                'kind': 'event'
            })
        
        logger.info(f"    Found {len(flashes_list)} flashes and {len(events_list)} events")
        
        # Read file blob for storage
        logger.info(f"  Reading file for storage...")
        with open(nc_path, 'rb') as f:
            file_blob = f.read()
        
        # Store raw file
        raw_id = db.store_raw_file(
            conn,
            source_url=source_url,
            source_time=source_time,
            file_format='NetCDF4',
            blob=file_blob,
            bbox=None
        )
        
        if not raw_id:
            result['error'] = "Failed to store raw_file"
            return result
        
        # Insert events (both flashes and events)
        if len(flashes_list) > 0:
            db.insert_events(conn, flashes_list, raw_file_id=raw_id)
            result['flashes'] = len(flashes_list)
        
        if len(events_list) > 0:
            db.insert_events(conn, events_list, raw_file_id=raw_id)
            result['events'] = len(events_list)
        
        result['success'] = True
        result['raw_id'] = raw_id
        
    except Exception as e:
        result['error'] = str(e)
        logger.error(f"  Error ingesting file: {e}")
    
    return result


def scan_nc_files(data_path: Path, logger) -> list:
    """
    Recursively scan for .nc files in data directory.
    Returns list of Path objects.
    """
    nc_files = list(data_path.glob('**/OR_GLM-L2-LCFA*.nc'))
    logger.info(f"Found {len(nc_files)} .nc files to consider")
    return sorted(nc_files)


def main():
    parser = argparse.ArgumentParser(
        description='Batch ingest GLM files into PostgreSQL',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Ingest all files from default path
  python scripts/backfill_glm_to_postgres.py \\
    --dsn "host=127.0.0.1 port=6543 dbname=lightning user=user password=pass"
  
  # Ingest up to 50 files
  python scripts/backfill_glm_to_postgres.py \\
    --dsn "host=127.0.0.1 port=6543 dbname=lightning user=user password=pass" \\
    --limit 50
  
  # Ingest from custom path
  python scripts/backfill_glm_to_postgres.py \\
    --dsn "host=127.0.0.1 port=6543 dbname=lightning user=user password=pass" \\
    --data-path "data/raw/glm_20s_goes_test"
        '''
    )
    
    parser.add_argument(
        '--dsn',
        required=True,
        help='PostgreSQL DSN (e.g., "host=127.0.0.1 port=6543 dbname=lightning user=user password=pass")'
    )
    parser.add_argument(
        '--data-path',
        default='data/raw/glm_20s_goes',
        help='Path to scan for .nc files (default: data/raw/glm_20s_goes)'
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Maximum number of files to ingest (default: all)'
    )
    parser.add_argument(
        '--verbose',
        '-v',
        action='store_true',
        help='Enable debug logging'
    )
    
    args = parser.parse_args()
    
    logger = setup_logging(
        level=logging.DEBUG if args.verbose else logging.INFO
    )
    
    logger.info("=" * 70)
    logger.info("GLM Backfill Ingestion Script")
    logger.info("=" * 70)
    logger.info(f"Data path: {args.data_path}")
    logger.info(f"Limit: {args.limit if args.limit else 'all'}")
    
    # Validate data path
    data_path = Path(args.data_path)
    if not data_path.exists():
        logger.error(f"Data path does not exist: {data_path}")
        return 1
    
    # Connect to Postgres
    try:
        logger.info("Connecting to PostgreSQL...")
        conn = db.get_conn(args.dsn)
        logger.info("✓ Connected to PostgreSQL")
    except Exception as e:
        logger.error(f"Failed to connect to PostgreSQL: {e}")
        return 1
    
    # Scan for files
    logger.info("Scanning for .nc files...")
    nc_files = scan_nc_files(data_path, logger)
    
    if not nc_files:
        logger.warning("No .nc files found")
        return 0
    
    # Apply limit
    if args.limit:
        nc_files = nc_files[:args.limit]
    
    logger.info(f"Will process {len(nc_files)} file(s)")
    logger.info("=" * 70)
    
    # Ingest files
    start_time = time.time()
    stats = {
        'total_files': len(nc_files),
        'ingested': 0,
        'skipped': 0,
        'failed': 0,
        'total_flashes': 0,
        'total_events': 0,
    }
    
    for idx, nc_path in enumerate(nc_files, 1):
        elapsed = time.time() - start_time
        rate = idx / elapsed if elapsed > 0 else 0
        remaining = (stats['total_files'] - idx) / rate if rate > 0 else 0
        
        logger.info(f"[{idx}/{stats['total_files']}] ({int(elapsed)}s elapsed, "
                   f"{int(remaining)}s remaining) Processing: {nc_path.name}")
        
        result = ingest_file(conn, nc_path, args.dsn, logger)
        
        if result['success']:
            if result['error'] and 'already ingested' in result['error']:
                stats['skipped'] += 1
                logger.info(f"  ⊘ Skipped (already in database)")
            else:
                stats['ingested'] += 1
                stats['total_flashes'] += result['flashes']
                stats['total_events'] += result['events']
                logger.info(f"  ✓ Success (ID: {result['raw_id']}, "
                           f"{result['flashes']} flashes, {result['events']} events)")
        else:
            stats['failed'] += 1
            logger.error(f"  ✗ Failed: {result['error']}")
    
    # Summary
    total_elapsed = time.time() - start_time
    logger.info("=" * 70)
    logger.info("SUMMARY")
    logger.info("=" * 70)
    logger.info(f"Total files:      {stats['total_files']}")
    logger.info(f"Ingested:         {stats['ingested']}")
    logger.info(f"Skipped:          {stats['skipped']}")
    logger.info(f"Failed:           {stats['failed']}")
    logger.info(f"Total flashes:    {stats['total_flashes']}")
    logger.info(f"Total events:     {stats['total_events']}")
    logger.info(f"Total time:       {int(total_elapsed)}s ({total_elapsed/60:.1f}m)")
    logger.info(f"Rate:             {stats['ingested']/total_elapsed:.2f} files/sec")
    
    conn.close()
    
    return 0 if stats['failed'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
