"""Storm Cell Detector — DBSCAN clustering of lightning flashes.

Implements Fase 1 (Identificação de Células) using density-based spatial
clustering with the haversine metric.  Each time frame's flashes are grouped
into StormCell objects.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Sequence

import numpy as np

from .models import StormCell
from .geo_utils import haversine_km_scalar, spherical_polygon_area_km2

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default parameters (calibrated for GLM mesoscale-γ cells)
# ---------------------------------------------------------------------------
DEFAULT_EPS_KM = 25.0       # Neighbourhood radius for DBSCAN
DEFAULT_MIN_SAMPLES = 5     # Minimum flashes to form a cell


def _convex_hull_2d(points: np.ndarray) -> np.ndarray:
    """Simple monotone-chain convex hull for 2-D points.

    ``points`` shape (N, 2).  Returns hull vertices in order, shape (M, 2).
    """

    pts = points[np.lexsort((points[:, 1], points[:, 0]))]
    if len(pts) <= 1:
        return pts

    def _cross(o: np.ndarray, a: np.ndarray, b: np.ndarray) -> float:
        return float((a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]))

    lower: list[np.ndarray] = []
    for p in pts:
        while len(lower) >= 2 and _cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    upper: list[np.ndarray] = []
    for p in reversed(pts):
        while len(upper) >= 2 and _cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    hull = lower[:-1] + upper[:-1]
    return np.array(hull) if hull else pts


def detect_cells(
    lats: np.ndarray,
    lons: np.ndarray,
    frame_time: datetime,
    *,
    eps_km: float = DEFAULT_EPS_KM,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    time_window_seconds: float = 300.0,
) -> list[StormCell]:
    """Cluster lightning flashes into storm cells using DBSCAN.

    Parameters
    ----------
    lats, lons : arrays of flash coordinates (degrees)
    frame_time : central timestamp of the frame (UTC)
    eps_km : neighbourhood radius in km
    min_samples : minimum number of flashes to form a cell
    time_window_seconds : duration of the frame in seconds (for flash_rate)

    Returns
    -------
    List of StormCell objects, one per cluster (noise points are discarded).
    """

    if len(lats) < min_samples:
        return []

    try:
        from sklearn.cluster import DBSCAN  # type: ignore
    except ImportError:
        logger.error("scikit-learn is required for nowcast: pip install scikit-learn")
        return []

    # DBSCAN with haversine metric expects radians
    coords_rad = np.column_stack([np.radians(lats), np.radians(lons)])
    eps_rad = eps_km / 6371.0

    db = DBSCAN(
        eps=eps_rad,
        min_samples=min_samples,
        metric="haversine",
        algorithm="ball_tree",
    )
    labels = db.fit_predict(coords_rad)

    unique_labels = set(labels)
    unique_labels.discard(-1)  # Remove noise

    cells: list[StormCell] = []

    for label in sorted(unique_labels):
        mask = labels == label
        clat = lats[mask]
        clon = lons[mask]
        n = int(mask.sum())

        # Centroid (simple mean — adequate for cells < 200km)
        centroid_lat = float(np.mean(clat))
        centroid_lon = float(np.mean(clon))

        # Bounding box
        bbox = (float(np.min(clat)), float(np.min(clon)),
                float(np.max(clat)), float(np.max(clon)))

        # Convex hull
        hull_pts = _convex_hull_2d(np.column_stack([clon, clat]))  # (lon, lat) for hull
        hull_lat = hull_pts[:, 1].tolist() if len(hull_pts) > 0 else []
        hull_lon = hull_pts[:, 0].tolist() if len(hull_pts) > 0 else []

        # Area from hull
        area = 0.0
        if len(hull_lat) >= 3:
            area = spherical_polygon_area_km2(hull_lat, hull_lon)

        # Max extent (pairwise max distance — approximate via bbox diagonal)
        max_extent = 0.0
        if n >= 2:
            max_extent = haversine_km_scalar(bbox[0], bbox[1], bbox[2], bbox[3])

        # Flash rate
        tw_min = max(1.0, time_window_seconds / 60.0)
        flash_rate = n / tw_min

        cell = StormCell(
            cell_id=f"cell_{label}_{uuid.uuid4().hex[:6]}",
            frame_time=frame_time,
            centroid_lat=centroid_lat,
            centroid_lon=centroid_lon,
            flash_count=n,
            area_km2=round(area, 1),
            max_extent_km=round(max_extent, 1),
            flash_rate=round(flash_rate, 2),
            bbox=bbox,
            points_lat=clat.tolist(),
            points_lon=clon.tolist(),
            hull_lat=hull_lat,
            hull_lon=hull_lon,
        )
        cells.append(cell)

    logger.info(
        "Detector: %d flashes → %d cells (eps=%.0fkm, min=%d, noise=%d)",
        len(lats), len(cells), eps_km, min_samples,
        int((labels == -1).sum()),
    )

    return cells
