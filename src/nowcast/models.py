"""Data models for the Sentinel Nowcast Engine.

All domain objects used across the pipeline:
Detector → Descriptor → Tracker → Forecaster.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class StormCell:
    """A spatially clustered group of lightning flashes within a single time frame."""

    cell_id: str                          # Unique identifier within the frame
    frame_time: datetime                  # Central timestamp of the frame (UTC)
    centroid_lat: float                   # Weighted centroid latitude
    centroid_lon: float                   # Weighted centroid longitude
    flash_count: int                      # Number of flashes in the cluster
    event_count: int = 0                  # Number of events (if available)
    area_km2: float = 0.0                 # Approximate area from convex hull
    max_extent_km: float = 0.0           # Maximum pairwise distance between points
    flash_rate: float = 0.0              # Flashes per minute
    bbox: tuple[float, float, float, float] = (0, 0, 0, 0)  # min_lat, min_lon, max_lat, max_lon
    points_lat: list[float] = field(default_factory=list)
    points_lon: list[float] = field(default_factory=list)
    hull_lat: list[float] = field(default_factory=list)      # Convex hull vertices
    hull_lon: list[float] = field(default_factory=list)


@dataclass
class VelocitySnapshot:
    """A single velocity observation at a point in time."""

    velocity_kmh: float
    bearing_deg: float                    # 0=N, 90=E, 180=S, 270=W
    timestamp: datetime


@dataclass
class CellTrack:
    """A temporal track linking the same storm cell across consecutive frames."""

    track_id: str                         # Persistent UUID
    cells: list[StormCell] = field(default_factory=list)
    velocity_kmh: float = 0.0            # Current smoothed velocity
    bearing_deg: float = 0.0             # Current smoothed bearing
    velocity_history: list[VelocitySnapshot] = field(default_factory=list)
    status: str = "new"                  # 'new' | 'active' | 'dissipating'
    confidence: float = 0.0              # 0.0–1.0
    missed_frames: int = 0               # Frames without a match


@dataclass
class Projection:
    """A single future position projection for a storm cell."""

    minutes_ahead: int
    lat: float
    lon: float
    confidence: float                     # Decayed confidence at this horizon


@dataclass
class ETAResult:
    """Estimated Time of Arrival for a storm cell impacting a service taker."""

    taker_id: int
    taker_name: str
    cell_id: str                          # Track ID of the approaching cell
    minutes_to_impact: int
    ring_km: int                          # Impact ring (30 or 50 km)
    projected_lat: float                  # Cell position at impact time
    projected_lon: float
    confidence: float
    velocity_kmh: float
    bearing_deg: float
    bearing_label: str                    # Human-readable: "NE", "SW", etc.
    approaching: bool                     # True if distance is decreasing


@dataclass
class CellReport:
    """Report for a single tracked cell, ready for JSON serialisation."""

    cell_id: str
    centroid_lat: float
    centroid_lon: float
    flash_count: int
    area_km2: float
    velocity_kmh: float
    bearing_deg: float
    bearing_label: str
    confidence: float
    status: str
    projections: list[Projection] = field(default_factory=list)
    hull_lat: list[float] = field(default_factory=list)
    hull_lon: list[float] = field(default_factory=list)


@dataclass
class NowcastReport:
    """Complete nowcast result for one cycle, consumed by the REST API."""

    generated_at_utc: datetime
    frame_count: int                      # Number of frames analysed
    cells: list[CellReport] = field(default_factory=list)
    impacts: list[ETAResult] = field(default_factory=list)
