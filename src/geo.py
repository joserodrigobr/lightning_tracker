from __future__ import annotations

from typing import Iterable

import numpy as np


EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: np.ndarray, lon2: np.ndarray) -> np.ndarray:
    """Vectorized great-circle distance from (lat1,lon1) to arrays (lat2,lon2)."""

    lat1r = np.radians(lat1)
    lon1r = np.radians(lon1)
    lat2r = np.radians(lat2.astype(np.float64))
    lon2r = np.radians(lon2.astype(np.float64))

    dlat = lat2r - lat1r
    dlon = lon2r - lon1r
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1r) * np.cos(lat2r) * np.sin(dlon / 2.0) ** 2
    c = 2.0 * np.arcsin(np.minimum(1.0, np.sqrt(a)))
    return EARTH_RADIUS_KM * c


def ring_index(dist_km: np.ndarray, radii_km: list[float]) -> np.ndarray:
    """Return ring index 0..len(radii)-1 for <= max radius, else len(radii).

    Uses non-overlapping ranges: (0..r1], (r1..r2], ...
    """

    bins = np.asarray(radii_km, dtype=np.float64)
    return np.digitize(dist_km, bins=bins, right=True)


def circle_points(lat_center: float, lon_center: float, radius_km: float, *, n: int = 361) -> tuple[np.ndarray, np.ndarray]:
    """Generate an approximate geodesic circle (spherical) in lat/lon."""

    lat1 = np.radians(lat_center)
    lon1 = np.radians(lon_center)
    ang_dist = radius_km / EARTH_RADIUS_KM

    bearings = np.linspace(0.0, 2.0 * np.pi, n)
    sin_lat1 = np.sin(lat1)
    cos_lat1 = np.cos(lat1)
    sin_ang = np.sin(ang_dist)
    cos_ang = np.cos(ang_dist)

    sin_lat2 = sin_lat1 * cos_ang + cos_lat1 * sin_ang * np.cos(bearings)
    lat2 = np.arcsin(np.clip(sin_lat2, -1.0, 1.0))

    y = np.sin(bearings) * sin_ang * cos_lat1
    x = cos_ang - sin_lat1 * np.sin(lat2)
    lon2 = lon1 + np.arctan2(y, x)

    return np.degrees(lat2), ((np.degrees(lon2) + 540.0) % 360.0) - 180.0


def convex_hull_lonlat(points: Iterable[tuple[float, float]]) -> list[tuple[float, float]]:
    """Monotonic chain convex hull.

    Input points are (lon, lat). Returns hull as list of (lon, lat).
    """

    pts = sorted(set(points))
    if len(pts) <= 1:
        return pts

    def cross(o: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    upper: list[tuple[float, float]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    # omit last point of each list (it's the starting point of the other list)
    return lower[:-1] + upper[:-1]
