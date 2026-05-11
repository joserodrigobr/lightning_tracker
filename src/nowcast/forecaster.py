"""Storm Cell Forecaster — trajectory projection and ETA calculation.

Implements Fase 4 (Projeção de Trajetória) and Fase 4b (Análise de Impacto).
Uses linear extrapolation of the displacement vector to project future cell
positions and detect intersection with service taker perimeters.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Sequence

from .models import CellTrack, Projection, ETAResult, CellReport
from .geo_utils import (
    bearing_label,
    circular_std,
    haversine_km_scalar,
    project_position,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Projection horizons
# ---------------------------------------------------------------------------
PROJECTION_HORIZONS_MIN = [15, 30, 60]   # Minutes ahead
IMPACT_RINGS_KM = [30, 50]               # Taker perimeter rings to check
MAX_PROJECTION_MIN = 120                  # Maximum projection horizon for ETA
ETA_STEP_MIN = 5                          # Step granularity for ETA search


@dataclass
class ServiceTakerInfo:
    """Lightweight taker info for ETA calculations."""
    taker_id: int
    name: str
    lat: float
    lon: float


# ---------------------------------------------------------------------------
# Projections
# ---------------------------------------------------------------------------

def project_track(track: CellTrack) -> list[Projection]:
    """Generate future position projections for a tracked cell.

    Returns a Projection for each horizon in PROJECTION_HORIZONS_MIN.
    """

    if track.velocity_kmh < 3.0:
        # Stationary cell — no meaningful projection
        cell = track.cells[-1]
        return [
            Projection(
                minutes_ahead=m,
                lat=cell.centroid_lat,
                lon=cell.centroid_lon,
                confidence=round(track.confidence * _time_decay(m), 2),
            )
            for m in PROJECTION_HORIZONS_MIN
        ]

    cell = track.cells[-1]
    projections: list[Projection] = []

    for minutes in PROJECTION_HORIZONS_MIN:
        hours = minutes / 60.0
        proj_lat, proj_lon = project_position(
            cell.centroid_lat, cell.centroid_lon,
            track.velocity_kmh, track.bearing_deg, hours,
        )
        conf = round(track.confidence * _time_decay(minutes), 2)
        projections.append(Projection(
            minutes_ahead=minutes,
            lat=round(proj_lat, 4),
            lon=round(proj_lon, 4),
            confidence=conf,
        ))

    return projections


# ---------------------------------------------------------------------------
# ETA impact analysis
# ---------------------------------------------------------------------------

def calculate_eta(
    track: CellTrack,
    taker: ServiceTakerInfo,
) -> ETAResult | None:
    """Calculate Estimated Time of Arrival for a storm cell impacting a taker.

    Iterates through projected positions at ETA_STEP_MIN intervals up to
    MAX_PROJECTION_MIN and checks whether the cell (accounting for its
    spatial extent) crosses the 30km or 50km rings.

    Returns None if no impact is projected.
    """

    if track.velocity_kmh < 3.0:
        return None

    cell = track.cells[-1]
    cell_radius_km = math.sqrt(max(1.0, cell.area_km2) / math.pi)

    # Current distance
    current_dist = haversine_km_scalar(
        cell.centroid_lat, cell.centroid_lon, taker.lat, taker.lon,
    )

    # Quick rejection: if cell is already very far and moving away, skip
    bearing_to_taker = _bearing_towards(
        cell.centroid_lat, cell.centroid_lon, taker.lat, taker.lon,
    )
    angle_diff = abs((track.bearing_deg - bearing_to_taker + 180) % 360 - 180)
    if current_dist > 300 and angle_diff > 90:
        return None  # Moving away from taker

    # Iterate projections
    for minutes in range(ETA_STEP_MIN, MAX_PROJECTION_MIN + 1, ETA_STEP_MIN):
        hours = minutes / 60.0
        proj_lat, proj_lon = project_position(
            cell.centroid_lat, cell.centroid_lon,
            track.velocity_kmh, track.bearing_deg, hours,
        )
        proj_dist = haversine_km_scalar(proj_lat, proj_lon, taker.lat, taker.lon)
        effective_dist = proj_dist - cell_radius_km

        # Check each ring from smallest to largest
        for ring_km in IMPACT_RINGS_KM:
            if effective_dist <= ring_km:
                approaching = proj_dist < current_dist
                conf = _eta_confidence(track, minutes)
                label = bearing_label(track.bearing_deg)

                logger.info(
                    "ETA: Track %s → %s in %d min (ring=%dkm, %.1fkm/h %s, conf=%.0f%%)",
                    track.track_id[:8], taker.name, minutes, ring_km,
                    track.velocity_kmh, label, conf * 100,
                )

                return ETAResult(
                    taker_id=taker.taker_id,
                    taker_name=taker.name,
                    cell_id=track.track_id,
                    minutes_to_impact=minutes,
                    ring_km=ring_km,
                    projected_lat=round(proj_lat, 4),
                    projected_lon=round(proj_lon, 4),
                    confidence=conf,
                    velocity_kmh=track.velocity_kmh,
                    bearing_deg=track.bearing_deg,
                    bearing_label=label,
                    approaching=approaching,
                )

    return None


def calculate_all_etas(
    tracks: list[CellTrack],
    takers: list[ServiceTakerInfo],
) -> list[ETAResult]:
    """Calculate ETAs for all active tracks against all takers.

    Returns only the closest ETA per (track, taker) pair.
    """

    results: list[ETAResult] = []
    for track in tracks:
        if track.velocity_kmh < 3.0:
            continue
        for taker in takers:
            eta = calculate_eta(track, taker)
            if eta is not None:
                results.append(eta)

    # Sort by urgency (earliest ETA first)
    results.sort(key=lambda e: e.minutes_to_impact)
    return results


# ---------------------------------------------------------------------------
# Build cell reports for API
# ---------------------------------------------------------------------------

def build_cell_reports(tracks: list[CellTrack]) -> list[CellReport]:
    """Convert active tracks into CellReport objects for the REST API."""

    reports: list[CellReport] = []
    for track in tracks:
        if not track.cells:
            continue
        cell = track.cells[-1]
        projections = project_track(track)
        label = bearing_label(track.bearing_deg)

        reports.append(CellReport(
            cell_id=track.track_id,
            centroid_lat=round(cell.centroid_lat, 4),
            centroid_lon=round(cell.centroid_lon, 4),
            flash_count=cell.flash_count,
            area_km2=cell.area_km2,
            velocity_kmh=track.velocity_kmh,
            bearing_deg=track.bearing_deg,
            bearing_label=label,
            confidence=track.confidence,
            status=track.status,
            projections=projections,
            hull_lat=cell.hull_lat,
            hull_lon=cell.hull_lon,
        ))

    return reports


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _time_decay(minutes_ahead: int) -> float:
    """Confidence decay factor for projection horizon."""
    return max(0.15, 1.0 - (minutes_ahead / 120.0) * 0.85)


def _eta_confidence(track: CellTrack, minutes_ahead: int) -> float:
    """Combined confidence for an ETA prediction."""

    # Time decay
    time_factor = _time_decay(minutes_ahead)

    # Directional stability
    if len(track.velocity_history) >= 3:
        bearings = [s.bearing_deg for s in track.velocity_history[-3:]]
        std = circular_std(bearings)
        stability = max(0.25, 1.0 - std / 45.0)
    else:
        stability = 0.5

    # Intensity (flash count)
    intensity = min(1.0, track.cells[-1].flash_count / 20.0)

    # Size (area) - larger cells are more likely to hit the target
    size_factor = min(1.0, track.cells[-1].area_km2 / 1000.0)
    size_factor = max(0.5, size_factor) # Minimum 0.5 for small but active cells

    return round(time_factor * stability * intensity * size_factor, 2)


def _bearing_towards(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Bearing from point 1 towards point 2."""
    import math as m
    lat1r, lat2r = m.radians(lat1), m.radians(lat2)
    dlon = m.radians(lon2 - lon1)
    x = m.sin(dlon) * m.cos(lat2r)
    y = m.cos(lat1r) * m.sin(lat2r) - m.sin(lat1r) * m.cos(lat2r) * m.cos(dlon)
    return (m.degrees(m.atan2(x, y)) + 360) % 360
