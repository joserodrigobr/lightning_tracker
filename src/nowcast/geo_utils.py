"""Geodesic utility functions for the Nowcast Engine.

Bearing calculation, destination point projection, and circular statistics.
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np

EARTH_RADIUS_KM = 6371.0088

# ---------------------------------------------------------------------------
# Compass labels
# ---------------------------------------------------------------------------

_COMPASS_LABELS = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
]


def bearing_label(deg: float) -> str:
    """Convert a bearing in degrees to a 16-point compass label."""
    idx = round(deg % 360 / 22.5) % 16
    return _COMPASS_LABELS[idx]


# ---------------------------------------------------------------------------
# Bearing between two points
# ---------------------------------------------------------------------------

def calculate_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the initial bearing (azimuth) from (lat1,lon1) to (lat2,lon2) in degrees [0,360)."""

    lat1r = math.radians(lat1)
    lat2r = math.radians(lat2)
    dlon = math.radians(lon2 - lon1)

    x = math.sin(dlon) * math.cos(lat2r)
    y = math.cos(lat1r) * math.sin(lat2r) - math.sin(lat1r) * math.cos(lat2r) * math.cos(dlon)

    brng = math.atan2(x, y)
    return (math.degrees(brng) + 360) % 360


# ---------------------------------------------------------------------------
# Destination point given bearing + distance
# ---------------------------------------------------------------------------

def project_position(lat: float, lon: float, velocity_kmh: float,
                     bearing_deg: float, hours_ahead: float) -> tuple[float, float]:
    """Project a future lat/lon using geodesic destination formula.

    Returns (lat, lon) in degrees.
    """

    distance_km = velocity_kmh * hours_ahead
    if distance_km < 0.01:
        return lat, lon

    angular_dist = distance_km / EARTH_RADIUS_KM

    lat1 = math.radians(lat)
    lon1 = math.radians(lon)
    bearing = math.radians(bearing_deg)

    sin_lat1 = math.sin(lat1)
    cos_lat1 = math.cos(lat1)
    sin_ang = math.sin(angular_dist)
    cos_ang = math.cos(angular_dist)

    lat2 = math.asin(sin_lat1 * cos_ang + cos_lat1 * sin_ang * math.cos(bearing))
    lon2 = lon1 + math.atan2(
        math.sin(bearing) * sin_ang * cos_lat1,
        cos_ang - sin_lat1 * math.sin(lat2),
    )

    return math.degrees(lat2), ((math.degrees(lon2) + 540) % 360) - 180


# ---------------------------------------------------------------------------
# Scalar haversine (single pair)
# ---------------------------------------------------------------------------

def haversine_km_scalar(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in km."""

    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return EARTH_RADIUS_KM * 2 * math.asin(min(1.0, math.sqrt(a)))


# ---------------------------------------------------------------------------
# Circular mean and std for bearings
# ---------------------------------------------------------------------------

def circular_mean(angles_deg: Sequence[float]) -> float:
    """Compute circular mean of angles in degrees, returned in [0, 360)."""

    if not angles_deg:
        return 0.0
    rads = [math.radians(a) for a in angles_deg]
    sin_sum = sum(math.sin(r) for r in rads)
    cos_sum = sum(math.cos(r) for r in rads)
    mean_rad = math.atan2(sin_sum, cos_sum)
    return (math.degrees(mean_rad) + 360) % 360


def circular_std(angles_deg: Sequence[float]) -> float:
    """Compute circular standard deviation (in degrees)."""

    if len(angles_deg) < 2:
        return 0.0
    rads = [math.radians(a) for a in angles_deg]
    n = len(rads)
    sin_sum = sum(math.sin(r) for r in rads)
    cos_sum = sum(math.cos(r) for r in rads)
    r_bar = math.sqrt(sin_sum ** 2 + cos_sum ** 2) / n
    # Circular variance = 1 - R_bar; std = sqrt(-2 * ln(R_bar))
    if r_bar >= 1.0:
        return 0.0
    if r_bar < 1e-10:
        return 180.0  # Maximum dispersion
    return math.degrees(math.sqrt(-2 * math.log(r_bar)))


# ---------------------------------------------------------------------------
# Convex hull area on a sphere (approximate)
# ---------------------------------------------------------------------------

def spherical_polygon_area_km2(lats: Sequence[float], lons: Sequence[float]) -> float:
    """Approximate area of a convex polygon on the sphere using the shoelace formula
    projected through Mercator-like scaling.  Good enough for cells < 200km across.
    """

    n = len(lats)
    if n < 3:
        return 0.0

    # Convert to radians
    lats_r = [math.radians(la) for la in lats]
    lons_r = [math.radians(lo) for lo in lons]

    # Spherical excess method (simplified)
    area_sr = 0.0
    for i in range(n):
        j = (i + 1) % n
        area_sr += lons_r[j] * math.sin(lats_r[i])
        area_sr -= lons_r[i] * math.sin(lats_r[j])
    area_sr = abs(area_sr) / 2.0

    return area_sr * EARTH_RADIUS_KM ** 2
