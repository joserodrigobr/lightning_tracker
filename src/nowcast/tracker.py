"""Storm Cell Tracker — temporal association via Hungarian algorithm.

Implements Fase 3 (Tracking) of the Nowcast Engine.  Associates cells across
consecutive frames using optimal assignment (cost = haversine distance between
centroids) and maintains persistent CellTrack objects with velocity history.

Inspired by FORTRACC centroid displacement methodology.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

import numpy as np

from .models import StormCell, CellTrack, VelocitySnapshot
from .geo_utils import (
    calculate_bearing,
    circular_mean,
    circular_std,
    haversine_km_scalar,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default parameters
# ---------------------------------------------------------------------------
MAX_MATCH_DISTANCE_KM = 80.0   # Maximum allowed centroid displacement between frames
MIN_TRACK_LENGTH = 2            # Minimum cells to compute a vector
MAX_MISSED_FRAMES = 2           # How many missed frames before dissipation
EMA_ALPHA = 0.5                 # Exponential moving average weight for smoothing


class CellTracker:
    """Maintains active tracks and associates new frames of cells.

    Usage::

        tracker = CellTracker()
        for frame_cells in frames:
            tracker.update(frame_cells)
        tracks = tracker.get_active_tracks()
    """

    def __init__(
        self,
        max_match_km: float = MAX_MATCH_DISTANCE_KM,
        max_missed: int = MAX_MISSED_FRAMES,
        ema_alpha: float = EMA_ALPHA,
    ):
        self._tracks: dict[str, CellTrack] = {}
        self._max_match_km = max_match_km
        self._max_missed = max_missed
        self._ema_alpha = ema_alpha

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    def update(self, cells: list[StormCell]) -> None:
        """Incorporate a new frame of detected cells into the tracking state."""

        if not cells and not self._tracks:
            return

        active_ids = [tid for tid, t in self._tracks.items() if t.status != "dissipating"]
        active_tracks = [self._tracks[tid] for tid in active_ids]

        if not active_tracks and not cells:
            return

        # Build cost matrix: rows = existing tracks, cols = new cells
        if active_tracks and cells:
            cost = self._build_cost_matrix(active_tracks, cells)
            row_idx, col_idx = self._hungarian_assignment(cost)
        else:
            row_idx, col_idx = [], []

        matched_track_indices: set[int] = set()
        matched_cell_indices: set[int] = set()

        # Process matches
        for r, c in zip(row_idx, col_idx):
            dist = cost[r, c]
            if dist > self._max_match_km:
                continue  # Too far — not a valid match
            track = active_tracks[r]
            cell = cells[c]
            self._extend_track(track, cell)
            matched_track_indices.add(r)
            matched_cell_indices.add(c)

        # Unmatched tracks → increment missed counter
        for i, track in enumerate(active_tracks):
            if i not in matched_track_indices:
                track.missed_frames += 1
                if track.missed_frames > self._max_missed:
                    track.status = "dissipating"
                    logger.debug("Track %s → dissipating (missed %d frames)", track.track_id, track.missed_frames)

        # Unmatched cells → create new tracks
        for j, cell in enumerate(cells):
            if j not in matched_cell_indices:
                self._create_track(cell)

        # Purge old dissipating tracks (keep for 1 extra cycle for reporting)
        to_remove = [tid for tid, t in self._tracks.items()
                     if t.status == "dissipating" and t.missed_frames > self._max_missed + 1]
        for tid in to_remove:
            del self._tracks[tid]

    def get_active_tracks(self) -> list[CellTrack]:
        """Return all tracks that have at least MIN_TRACK_LENGTH cells and a valid vector."""
        return [
            t for t in self._tracks.values()
            if t.status in ("active", "new") and len(t.cells) >= MIN_TRACK_LENGTH
        ]

    def get_all_tracks(self) -> list[CellTrack]:
        """Return all tracks including young and dissipating ones."""
        return list(self._tracks.values())

    # -----------------------------------------------------------------
    # Internal
    # -----------------------------------------------------------------

    def _build_cost_matrix(self, tracks: list[CellTrack], cells: list[StormCell]) -> np.ndarray:
        """Build an (M, N) cost matrix where cost = haversine distance between last track centroid and cell centroid."""

        m = len(tracks)
        n = len(cells)
        cost = np.full((m, n), 1e9, dtype=np.float64)

        for i, track in enumerate(tracks):
            last = track.cells[-1]
            for j, cell in enumerate(cells):
                cost[i, j] = haversine_km_scalar(
                    last.centroid_lat, last.centroid_lon,
                    cell.centroid_lat, cell.centroid_lon,
                )

        return cost

    @staticmethod
    def _hungarian_assignment(cost: np.ndarray) -> tuple[list[int], list[int]]:
        """Optimal assignment using scipy's linear_sum_assignment."""

        try:
            from scipy.optimize import linear_sum_assignment  # type: ignore
        except ImportError:
            logger.error("scipy is required for tracking: pip install scipy")
            return [], []

        row_ind, col_ind = linear_sum_assignment(cost)
        return row_ind.tolist(), col_ind.tolist()

    def _extend_track(self, track: CellTrack, cell: StormCell) -> None:
        """Add a new cell to an existing track and recalculate velocity."""

        prev = track.cells[-1]
        track.cells.append(cell)
        track.missed_frames = 0

        # Calculate raw velocity and bearing
        dt_hours = (cell.frame_time - prev.frame_time).total_seconds() / 3600.0
        if dt_hours <= 0:
            return

        dist_km = haversine_km_scalar(
            prev.centroid_lat, prev.centroid_lon,
            cell.centroid_lat, cell.centroid_lon,
        )
        raw_velocity = dist_km / dt_hours
        raw_bearing = calculate_bearing(
            prev.centroid_lat, prev.centroid_lon,
            cell.centroid_lat, cell.centroid_lon,
        )

        # Record raw observation
        snap = VelocitySnapshot(
            velocity_kmh=round(raw_velocity, 1),
            bearing_deg=round(raw_bearing, 1),
            timestamp=cell.frame_time,
        )
        track.velocity_history.append(snap)

        # Keep only last 6 observations
        if len(track.velocity_history) > 6:
            track.velocity_history = track.velocity_history[-6:]

        # Smooth with EMA (FORTRACC-style momentum correction)
        if len(track.velocity_history) >= 2:
            alpha = self._ema_alpha
            track.velocity_kmh = round(
                alpha * raw_velocity + (1 - alpha) * track.velocity_kmh, 1
            )
            recent_bearings = [s.bearing_deg for s in track.velocity_history[-3:]]
            track.bearing_deg = round(circular_mean(recent_bearings), 1)
        else:
            track.velocity_kmh = round(raw_velocity, 1)
            track.bearing_deg = round(raw_bearing, 1)

        # Calculate confidence
        track.confidence = self._calculate_track_confidence(track)

        # Update status
        if len(track.cells) >= MIN_TRACK_LENGTH:
            track.status = "active"

        logger.debug(
            "Track %s extended: %.1f km/h @ %.0f° (%s), confidence=%.2f",
            track.track_id[:8], track.velocity_kmh, track.bearing_deg,
            track.status, track.confidence,
        )

    def _create_track(self, cell: StormCell) -> None:
        """Create a new track from an unmatched cell."""

        track_id = uuid.uuid4().hex[:12]
        track = CellTrack(
            track_id=track_id,
            cells=[cell],
            status="new",
        )
        self._tracks[track_id] = track
        logger.debug("New track %s at (%.2f, %.2f) with %d flashes",
                     track_id[:8], cell.centroid_lat, cell.centroid_lon, cell.flash_count)

    @staticmethod
    def _calculate_track_confidence(track: CellTrack) -> float:
        """Confidence score based on track age, velocity stability, and intensity."""

        # Factor 1: Track maturity (more frames = higher confidence)
        maturity = min(1.0, len(track.cells) / 5.0)

        # Factor 2: Directional stability
        if len(track.velocity_history) >= 3:
            bearings = [s.bearing_deg for s in track.velocity_history[-3:]]
            std = circular_std(bearings)
            stability = max(0.3, 1.0 - std / 60.0)
        else:
            stability = 0.5

        # Factor 3: Intensity (flash count)
        last_cell = track.cells[-1]
        intensity = min(1.0, last_cell.flash_count / 15.0)

        return round(maturity * stability * intensity, 2)
