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


def _create_grid_polygon(lats: np.ndarray, lons: np.ndarray, grid_size: float = 0.05) -> tuple[list[float], list[float], float]:
    """Create a squared polygon based on point density grid.
    
    Parameters
    ----------
    lats, lons : coordinates
    grid_size : size of the square in degrees (0.05 ~ 5.5km)
    
    Returns
    -------
    (hull_lat, hull_lon, area_km2)
    """
    import shapely.geometry
    from shapely.ops import unary_union
    from .geo_utils import spherical_polygon_area_km2

    if len(lats) == 0:
        return [], [], 0.0

    # Find unique grid cells occupied by points
    # We use floor to bin coordinates into grid indices
    lat_indices = np.floor(lats / grid_size).astype(int)
    lon_indices = np.floor(lons / grid_size).astype(int)
    
    # Convert to list to avoid exhaustion and speed up multiple passes
    indices = list(zip(lat_indices, lon_indices))
    unique_cells = set(indices)
    
    # Adaptive dilation: expand more around high-density cells (core),
    # less around sparse cells (periphery). KDE-inspired approach.
    cell_counts = {}
    for key in indices:
        cell_counts[key] = cell_counts.get(key, 0) + 1
    
    if cell_counts:
        counts = list(cell_counts.values())
        density_threshold = np.median(counts) if len(counts) > 1 else 1
    else:
        density_threshold = 1
    
    dilated_cells = set()
    for cell_key in unique_cells:
        count = cell_counts.get(cell_key, 0)
        # High-density core: 2-cell buffer (anvil/outflow zone)
        # Low-density periphery: 1-cell buffer
        radius = 2 if count >= density_threshold else 1
        lat_idx, lon_idx = cell_key
        for i in range(-radius, radius + 1):
            for j in range(-radius, radius + 1):
                dilated_cells.add((lat_idx + i, lon_idx + j))
    
    squares = []
    for lat_idx, lon_idx in dilated_cells:
        # Create a box for this cell
        min_lat = lat_idx * grid_size
        max_lat = (lat_idx + 1) * grid_size
        min_lon = lon_idx * grid_size
        max_lon = (lon_idx + 1) * grid_size
        
        # shapely.geometry.box(minx, miny, maxx, maxy)
        # In our case x=lon, y=lat
        squares.append(shapely.geometry.box(min_lon, min_lat, max_lon, max_lat))
    
    if not squares:
        return [], [], 0.0
        
    # Merge all squares into a single (possibly multi) polygon
    merged = unary_union(squares)
    
    # We want the exterior of the largest polygon if it's a MultiPolygon
    if isinstance(merged, shapely.geometry.MultiPolygon):
        # Pick the largest one by area
        main_poly = max(merged.geoms, key=lambda p: p.area)
    elif isinstance(merged, shapely.geometry.Polygon):
        main_poly = merged
    else:
        return [], [], 0.0

    hull_lon, hull_lat = main_poly.exterior.xy
    hull_lon = hull_lon.tolist()
    hull_lat = hull_lat.tolist()
    
    # Calculate real-world area
    area = spherical_polygon_area_km2(hull_lat, hull_lon)
    
    return hull_lat, hull_lon, area


def detect_cells(
    lats: np.ndarray,
    lons: np.ndarray,
    frame_time: datetime,
    *,
    eps_km: float = DEFAULT_EPS_KM,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    time_window_seconds: float = 300.0,
    event_lats: Optional[np.ndarray] = None,
    event_lons: Optional[np.ndarray] = None,
) -> list[StormCell]:
    """Cluster lightning flashes into storm cells and define geometry using grid density.
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

        # Bounding box of flashes
        bbox = (float(np.min(clat)), float(np.min(clon)),
                float(np.max(clat)), float(np.max(clon)))

        # Identify events that belong to this cluster area
        poly_lats = clat
        poly_lons = clon
        
        if event_lats is not None and len(event_lats) > 0:
            ev_mask = (event_lats >= bbox[0] - 0.1) & (event_lats <= bbox[2] + 0.1) & \
                      (event_lons >= bbox[1] - 0.1) & (event_lons <= bbox[3] + 0.1)
            
            if ev_mask.any():
                poly_lats = np.concatenate([clat, event_lats[ev_mask]])
                poly_lons = np.concatenate([clon, event_lons[ev_mask]])

        # Centroid (using all points in the cluster + associated events)
        centroid_lat = float(np.mean(poly_lats))
        centroid_lon = float(np.mean(poly_lons))

        # Geometry (Density Grid Polygon)
        hull_lat, hull_lon, area = _create_grid_polygon(poly_lats, poly_lons, grid_size=0.05)

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
