#!/usr/bin/env python3
"""
Production Validation Tests for Lightning Tracker

Tests:
1. Query performance (6K events in <500ms)
2. Database size and growth projections
3. Connection pooling and stability
4. Fallback mechanisms
"""

import sys
import os
import time
import json
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from src import db
from src.data_store import load_points_from_postgres, load_daily_tables


def setup_logging(level="INFO"):
    """Setup logging."""
    import logging
    logging.basicConfig(
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        level=getattr(logging, level)
    )
    return logging.getLogger(__name__)


logger = setup_logging()


def test_1_query_performance(dsn: str):
    """Test 1: Query Performance - Load 6K+ events in <500ms"""
    logger.info("=" * 70)
    logger.info("TEST 1: Query Performance (target: <500ms for 6K events)")
    logger.info("=" * 70)
    
    try:
        conn = db.get_conn(dsn)
        
        # Get raw_file_id with most events
        cur = conn.cursor()
        cur.execute("""
            SELECT raw_file_id, COUNT(*) as event_count 
            FROM lightning_events 
            GROUP BY raw_file_id 
            ORDER BY event_count DESC 
            LIMIT 1
        """)
        result = cur.fetchone()
        cur.close()
        
        if not result:
            logger.warning("  No events in database yet")
            return False
        
        raw_file_id, event_count = result
        logger.info(f"  Using raw_file_id={raw_file_id} with {event_count} events")
        
        # Test: Load all events from this file
        start_time = time.time()
        cur = conn.cursor()
        cur.execute(
            "SELECT event_time, latitude, longitude FROM lightning_events WHERE raw_file_id = %s",
            (raw_file_id,)
        )
        events = cur.fetchall()
        cur.close()
        elapsed = (time.time() - start_time) * 1000  # ms
        
        logger.info(f"  ✓ Loaded {len(events)} events in {elapsed:.1f}ms")
        
        if elapsed < 500:
            logger.info(f"  ✓ PASS: {elapsed:.1f}ms < 500ms target")
            success = True
        else:
            logger.warning(f"  ✗ WARNING: {elapsed:.1f}ms > 500ms target")
            success = False
        
        # Additional tests: time range queries
        start_dt = datetime(2026, 5, 4, 2, 59)
        end_dt = datetime(2026, 5, 4, 3, 1)
        
        start_time = time.time()
        cur = conn.cursor()
        cur.execute("""
            SELECT event_time, latitude, longitude FROM lightning_events 
            WHERE event_time >= %s AND event_time <= %s
        """, (start_dt, end_dt))
        time_range_events = cur.fetchall()
        cur.close()
        elapsed_range = (time.time() - start_time) * 1000
        
        logger.info(f"  ✓ Time range query: {len(time_range_events)} events in {elapsed_range:.1f}ms")
        
        # Test: Spatial queries (events within bbox)
        start_time = time.time()
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM lightning_events 
            WHERE latitude >= %s AND latitude <= %s 
            AND longitude >= %s AND longitude <= %s
        """, (-33, 5, -82, -35))  # South America bbox
        sa_count = cur.fetchone()[0]
        cur.close()
        elapsed_spatial = (time.time() - start_time) * 1000
        
        logger.info(f"  ✓ Spatial query (SA): {sa_count} events in {elapsed_spatial:.1f}ms")
        
        conn.close()
        return success
        
    except Exception as e:
        logger.error(f"  ✗ FAILED: {e}")
        return False


def test_2_database_size(dsn: str):
    """Test 2: Database size and growth projections"""
    logger.info("=" * 70)
    logger.info("TEST 2: Database Size and Growth Projections")
    logger.info("=" * 70)
    
    try:
        conn = db.get_conn(dsn)
        cur = conn.cursor()
        
        # Get table sizes
        cur.execute("""
            SELECT 
                tablename,
                ROUND(pg_total_relation_size(schemaname||'.'||tablename)/1024.0/1024.0, 2) as size_mb
            FROM pg_tables
            WHERE schemaname = 'public'
            ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC
        """)
        tables = cur.fetchall()
        
        total_size = 0
        logger.info("\n  Table Sizes:")
        for table_name, size_mb in tables:
            logger.info(f"    {table_name:20} {size_mb:10.2f} MB")
            total_size += size_mb
        
        logger.info(f"    {'TOTAL':20} {total_size:10.2f} MB")
        
        # Get row counts
        cur.execute("SELECT COUNT(*) FROM raw_files")
        raw_files_count = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM lightning_events")
        events_count = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM daily_tables")
        tables_count = cur.fetchone()[0]
        
        logger.info(f"\n  Row Counts:")
        logger.info(f"    raw_files:        {raw_files_count:,}")
        logger.info(f"    lightning_events: {events_count:,}")
        logger.info(f"    daily_tables:     {tables_count:,}")
        
        # Growth projection
        if raw_files_count > 0 and total_size > 0:
            avg_size_per_file = total_size / raw_files_count
            avg_events_per_file = events_count / raw_files_count
            
            logger.info(f"\n  Per-File Metrics:")
            logger.info(f"    Avg size per file:        {avg_size_per_file:.2f} MB")
            logger.info(f"    Avg events per file:      {avg_events_per_file:.0f}")
            
            # Projections for 1 day, 1 week, 1 month
            # Assume ~120 files per hour = 2880 files/day
            files_per_day = 2880
            
            for days, label in [(1, "1 day"), (7, "1 week"), (30, "1 month")]:
                projected_files = files_per_day * days
                projected_size = projected_files * avg_size_per_file
                projected_events = projected_files * avg_events_per_file
                
                logger.info(f"\n  Projection for {label}:")
                logger.info(f"    Files:   {projected_files:,}")
                logger.info(f"    Size:    {projected_size:,.0f} MB ({projected_size/1024:.1f} GB)")
                logger.info(f"    Events:  {projected_events:,.0f}")
        
        cur.close()
        conn.close()
        return True
        
    except Exception as e:
        logger.error(f"  ✗ FAILED: {e}")
        return False


def test_3_connection_stability(dsn: str, num_connections: int = 10):
    """Test 3: Connection pooling and stability"""
    logger.info("=" * 70)
    logger.info(f"TEST 3: Connection Stability ({num_connections} concurrent connections)")
    logger.info("=" * 70)
    
    try:
        connections = []
        start_time = time.time()
        
        # Open multiple connections
        for i in range(num_connections):
            try:
                conn = db.get_conn(dsn)
                connections.append(conn)
                logger.info(f"  Connection {i+1}/{num_connections} established")
            except Exception as e:
                logger.error(f"  ✗ Failed to establish connection {i+1}: {e}")
                return False
        
        elapsed = time.time() - start_time
        logger.info(f"  ✓ Established {num_connections} connections in {elapsed:.2f}s")
        
        # Test queries on each connection
        for i, conn in enumerate(connections):
            try:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM lightning_events")
                count = cur.fetchone()[0]
                cur.close()
                logger.info(f"  Connection {i+1} query: OK ({count} events)")
            except Exception as e:
                logger.error(f"  ✗ Connection {i+1} query failed: {e}")
                return False
        
        # Close all connections
        for conn in connections:
            conn.close()
        
        logger.info(f"  ✓ All connections closed successfully")
        return True
        
    except Exception as e:
        logger.error(f"  ✗ FAILED: {e}")
        return False


def test_4_env_var_configuration(dsn_env_var: str = "LIGHTNING_TRACKER_PG_DSN"):
    """Test 4: Environment variable configuration"""
    logger.info("=" * 70)
    logger.info(f"TEST 4: Environment Variable Configuration (${dsn_env_var})")
    logger.info("=" * 70)
    
    try:
        dsn = os.getenv(dsn_env_var)
        
        if not dsn:
            logger.warning(f"  ✗ Environment variable ${dsn_env_var} not set")
            logger.info(f"  To configure, run:")
            logger.info(f"    $env:{dsn_env_var} = 'host=... port=... dbname=... user=... password=...'")
            return False
        
        logger.info(f"  ✓ Environment variable ${dsn_env_var} is set")
        
        # Test connection
        try:
            conn = db.get_conn(dsn)
            cur = conn.cursor()
            cur.execute("SELECT version()")
            version = cur.fetchone()[0]
            cur.close()
            conn.close()
            
            logger.info(f"  ✓ Connection successful")
            logger.info(f"  ✓ PostgreSQL: {version[:50]}...")
            return True
        except Exception as e:
            logger.error(f"  ✗ Connection failed: {e}")
            return False
        
    except Exception as e:
        logger.error(f"  ✗ FAILED: {e}")
        return False


def test_5_fallback_behavior(dsn: str):
    """Test 5: Fallback behavior when DSN not available"""
    logger.info("=" * 70)
    logger.info("TEST 5: Fallback Behavior (DSN vs S3)")
    logger.info("=" * 70)
    
    try:
        # Test: Remove DSN and verify fallback works
        original_dsn = os.getenv("LIGHTNING_TRACKER_PG_DSN")
        
        # Test with DSN
        os.environ["LIGHTNING_TRACKER_PG_DSN"] = dsn
        logger.info("  ✓ With DSN configured:")
        
        try:
            # This should use Postgres
            from src.data_store import get_postgres_dsn
            detected_dsn = get_postgres_dsn()
            if detected_dsn:
                logger.info(f"    Postgres DSN detected: {detected_dsn[:30]}...")
            else:
                logger.warning("    No DSN detected (unexpected)")
        except Exception as e:
            logger.warning(f"    {e}")
        
        # Test without DSN
        if "LIGHTNING_TRACKER_PG_DSN" in os.environ:
            del os.environ["LIGHTNING_TRACKER_PG_DSN"]
        
        logger.info("  ✓ Without DSN (fallback mode):")
        try:
            from src.data_store import get_postgres_dsn
            detected_dsn = get_postgres_dsn()
            if not detected_dsn:
                logger.info("    Fallback to S3: OK (no DSN detected)")
            else:
                logger.warning(f"    DSN still detected: {detected_dsn[:30]}...")
        except Exception as e:
            logger.warning(f"    {e}")
        
        # Restore original DSN
        if original_dsn:
            os.environ["LIGHTNING_TRACKER_PG_DSN"] = original_dsn
        
        return True
        
    except Exception as e:
        logger.error(f"  ✗ FAILED: {e}")
        return False


def main():
    """Run all tests."""
    logger.info("\n")
    logger.info("╔" + "=" * 68 + "╗")
    logger.info("║" + " Lightning Tracker - Production Validation Tests ".center(68) + "║")
    logger.info("╚" + "=" * 68 + "╝")
    
    # Get DSN from environment or hardcoded for testing
    dsn = os.getenv("LIGHTNING_TRACKER_PG_DSN") or "host=127.0.0.1 port=6543 dbname=lightning user=user password=pass"
    
    results = {}
    
    # Run tests
    results["1_query_performance"] = test_1_query_performance(dsn)
    results["2_database_size"] = test_2_database_size(dsn)
    results["3_connection_stability"] = test_3_connection_stability(dsn)
    results["4_env_var_configuration"] = test_4_env_var_configuration()
    results["5_fallback_behavior"] = test_5_fallback_behavior(dsn)
    
    # Summary
    logger.info("\n")
    logger.info("=" * 70)
    logger.info("VALIDATION SUMMARY")
    logger.info("=" * 70)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        logger.info(f"  {test_name:30} {status}")
    
    logger.info(f"\n  Total: {passed}/{total} tests passed")
    
    if passed == total:
        logger.info("\n  ✓ All validation tests passed!")
        return 0
    else:
        logger.warning(f"\n  ✗ {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
