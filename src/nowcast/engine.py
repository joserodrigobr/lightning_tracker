#!/usr/bin/env python3
"""Sentinel Nowcast Engine — main orchestrator.

Runs one complete nowcast cycle:
  1. Query recent flashes from PostgreSQL
  2. Build time frames and detect cells (DBSCAN)
  3. Track cells across frames (Hungarian)
  4. Project trajectories and calculate ETAs
  5. Output NowcastReport as JSON to stdout

Can be invoked as:
    python -m src.nowcast.engine --settings config/settings.yaml [--taker-ids 1,2,3]

Or imported and called programmatically:
    from src.nowcast.engine import run_nowcast_cycle
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import numpy as np

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.nowcast.models import NowcastReport
from src.nowcast.detector import detect_cells
from src.nowcast.tracker import CellTracker
from src.nowcast.forecaster import (
    ServiceTakerInfo,
    build_cell_reports,
    calculate_all_etas,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
FRAME_WINDOW_SEC = 300        # 5-minute frames
NUM_FRAMES = 6                # Analyse last 30 minutes (6 × 5min)
LOOKBACK_MINUTES = 30         # Total lookback window
EPS_KM = 25.0
MIN_SAMPLES = 5


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_events_from_postgres(
    dsn: str,
    start_utc: datetime,
    end_utc: datetime,
    kind: str = "flash",
    max_points: int = 100_000,
) -> list[dict]:
    """Load lightning events from PostgreSQL.

    Returns list of dicts with keys: event_time, latitude, longitude.
    """

    try:
        from src.db import get_conn
    except ImportError:
        logger.error("src.db module not available")
        return []

    events: list[dict] = []
    try:
        conn = get_conn(dsn)
        cur = conn.cursor()
        cur.execute(
            """SELECT event_time, latitude, longitude
               FROM lightning_events
               WHERE event_time >= %s AND event_time <= %s
                 AND kind = %s
               ORDER BY event_time ASC
               LIMIT %s""",
            (start_utc, end_utc, kind, max_points),
        )
        for row in cur.fetchall():
            events.append({
                "event_time": row[0] if isinstance(row[0], datetime) else datetime.fromisoformat(str(row[0])),
                "latitude": float(row[1]),
                "longitude": float(row[2]),
            })
        cur.close()
        conn.close()
    except Exception as e:
        logger.error("Failed to load events from PostgreSQL: %s", e)

    return events


def _load_takers(settings_path: Optional[Path] = None) -> list[ServiceTakerInfo]:
    """Load service takers from SQLite database or CSV fallback."""

    takers: list[ServiceTakerInfo] = []

    # Try SQLite first
    sqlite_path = Path("webapp/backend/db/service_takers.sqlite")
    if sqlite_path.exists():
        try:
            import sqlite3
            conn = sqlite3.connect(str(sqlite_path))
            cur = conn.cursor()
            cur.execute("SELECT id, nome_plataforma, latitude, longitude FROM tomadores_servico")
            for row in cur.fetchall():
                takers.append(ServiceTakerInfo(
                    taker_id=int(row[0]),
                    name=str(row[1]),
                    lat=float(row[2]),
                    lon=float(row[3]),
                ))
            conn.close()
            return takers
        except Exception as e:
            logger.warning("SQLite load failed: %s", e)

    # Fallback to CSV
    csv_path = Path("config/service_takers.csv")
    if csv_path.exists():
        try:
            import csv
            with csv_path.open("r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f, delimiter=";")
                for row in reader:
                    tid = int(row.get("N", "0").strip())
                    if tid <= 0:
                        continue
                    name = (row.get("UNIDADE TOMADORA DE SERVIÇO") or row.get("MUNICIPIO", "")).strip()
                    lat = float(row.get("Latitude", "0").replace(",", "."))
                    lon = float(row.get("Longitude", "0").replace(",", "."))
                    takers.append(ServiceTakerInfo(taker_id=tid, name=name, lat=lat, lon=lon))
        except Exception as e:
            logger.warning("CSV load failed: %s", e)

    return takers


# ---------------------------------------------------------------------------
# Core cycle
# ---------------------------------------------------------------------------

def run_nowcast_cycle(
    dsn: str,
    taker_ids: Optional[list[int]] = None,
    now_utc: Optional[datetime] = None,
) -> NowcastReport:
    """Execute one complete nowcast cycle and return a NowcastReport.

    Parameters
    ----------
    dsn : PostgreSQL DSN string
    taker_ids : optional list of taker IDs to analyse (None = all)
    now_utc : reference time (defaults to datetime.now(UTC))
    """

    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    start_utc = now_utc - timedelta(minutes=LOOKBACK_MINUTES)

    logger.info("Nowcast cycle: %s → %s", start_utc.isoformat(), now_utc.isoformat())

    # 1. Load events
    events = _load_events_from_postgres(dsn, start_utc, now_utc, kind="flash")
    if not events:
        logger.warning("No flash events in the last %d minutes", LOOKBACK_MINUTES)
        return NowcastReport(generated_at_utc=now_utc, frame_count=0)

    logger.info("Loaded %d flash events", len(events))

    # 2. Build time frames
    frames = _build_frames(events, now_utc, NUM_FRAMES, FRAME_WINDOW_SEC)
    logger.info("Built %d frames", len(frames))

    # 3. Detect cells in each frame and track across frames
    tracker = CellTracker(max_match_km=80.0)

    for i, (frame_time, frame_events) in enumerate(frames):
        if not frame_events:
            tracker.update([])
            continue

        lats = np.array([e["latitude"] for e in frame_events])
        lons = np.array([e["longitude"] for e in frame_events])

        cells = detect_cells(
            lats, lons, frame_time,
            eps_km=EPS_KM,
            min_samples=MIN_SAMPLES,
            time_window_seconds=FRAME_WINDOW_SEC,
        )
        tracker.update(cells)
        logger.info("Frame %d/%d (%s): %d events → %d cells",
                     i + 1, len(frames), frame_time.strftime("%H:%M"), len(frame_events), len(cells))

    # 4. Get active tracks and generate projections
    active_tracks = tracker.get_active_tracks()
    logger.info("Active tracks with vectors: %d", len(active_tracks))

    cell_reports = build_cell_reports(active_tracks)

    # 5. Load takers and calculate ETAs
    takers = _load_takers()
    if taker_ids:
        takers = [t for t in takers if t.taker_id in taker_ids]

    impacts = calculate_all_etas(active_tracks, takers)
    logger.info("Impact predictions: %d", len(impacts))

    return NowcastReport(
        generated_at_utc=now_utc,
        frame_count=len(frames),
        cells=cell_reports,
        impacts=impacts,
    )


def _build_frames(
    events: list[dict],
    now_utc: datetime,
    num_frames: int,
    window_sec: int,
) -> list[tuple[datetime, list[dict]]]:
    """Split events into fixed-width time frames working backwards from now.

    Returns list of (frame_center_time, events_in_frame) newest-last.
    """

    frames: list[tuple[datetime, list[dict]]] = []

    for i in range(num_frames, 0, -1):
        frame_end = now_utc - timedelta(seconds=(i - 1) * window_sec)
        frame_start = frame_end - timedelta(seconds=window_sec)
        frame_center = frame_start + timedelta(seconds=window_sec / 2)

        frame_events = [
            e for e in events
            if frame_start <= e["event_time"] < frame_end
        ]
        frames.append((frame_center, frame_events))

    return frames


# ---------------------------------------------------------------------------
# JSON serialisation
# ---------------------------------------------------------------------------

def _report_to_dict(report: NowcastReport) -> dict:
    """Convert a NowcastReport to a JSON-serialisable dict."""

    return {
        "generatedAtUtc": report.generated_at_utc.isoformat(),
        "frameCount": report.frame_count,
        "cells": [
            {
                "cellId": c.cell_id,
                "centroidLat": c.centroid_lat,
                "centroidLon": c.centroid_lon,
                "flashCount": c.flash_count,
                "areaKm2": c.area_km2,
                "velocityKmh": c.velocity_kmh,
                "bearingDeg": c.bearing_deg,
                "bearingLabel": c.bearing_label,
                "confidence": c.confidence,
                "status": c.status,
                "hullLat": c.hull_lat,
                "hullLon": c.hull_lon,
                "projections": [
                    {
                        "minutes": p.minutes_ahead,
                        "lat": p.lat,
                        "lon": p.lon,
                        "confidence": p.confidence,
                    }
                    for p in c.projections
                ],
            }
            for c in report.cells
        ],
        "impacts": [
            {
                "takerId": e.taker_id,
                "takerName": e.taker_name,
                "cellId": e.cell_id,
                "etaMinutes": e.minutes_to_impact,
                "ringKm": e.ring_km,
                "projectedLat": e.projected_lat,
                "projectedLon": e.projected_lon,
                "confidence": e.confidence,
                "velocityKmh": e.velocity_kmh,
                "bearingDeg": e.bearing_deg,
                "bearingLabel": e.bearing_label,
                "approaching": e.approaching,
            }
            for e in report.impacts
        ],
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Sentinel Nowcast Engine — storm cell tracking")
    parser.add_argument("--settings", default="config/settings.yaml", help="Path to settings.yaml")
    parser.add_argument("--taker-ids", default=None, help="Comma-separated taker IDs (default: all)")
    args = parser.parse_args()

    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        level=logging.INFO,
    )

    # Get DSN
    dsn = os.environ.get("LIGHTNING_TRACKER_PG_DSN", "").strip()
    if not dsn:
        sys.stderr.write("Error: LIGHTNING_TRACKER_PG_DSN environment variable not set\n")
        return 1

    taker_ids = None
    if args.taker_ids:
        taker_ids = [int(x.strip()) for x in args.taker_ids.split(",") if x.strip()]

    report = run_nowcast_cycle(dsn, taker_ids=taker_ids)

    # Output JSON to stdout
    result = _report_to_dict(report)
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
    sys.stdout.write("\n")
    sys.stdout.flush()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
