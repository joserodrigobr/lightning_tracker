from __future__ import annotations

import argparse
import os
import sys
import time
import textwrap
from functools import lru_cache
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from io import BytesIO
from pathlib import Path
from typing import cast

import numpy as np
import pandas as pd
import logging

# Force headless rendering for web/server usage.
os.environ.setdefault("MPLBACKEND", "Agg")

import matplotlib
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
from matplotlib.colors import Colormap
from matplotlib.offsetbox import AnnotationBbox, OffsetImage
from matplotlib.lines import Line2D
from matplotlib.patches import Polygon
import threading

try:
    import geobr  # type: ignore
except Exception:
    geobr = None

try:
    import geopandas as gpd  # type: ignore
except Exception:
    gpd = None

from .background import AbiIrBackgroundProvider, BackgroundImage
from .data_store import get_postgres_dsn, load_points_from_postgres
from .config import load_settings
from .downloader import GLMDownloader
from .geo import circle_points, convex_hull_lonlat, haversine_km
from .processor import extract_points_from_lcfa


@dataclass(frozen=True)
class RenderParams:
    taker_name: str
    lat0: float
    lon0: float
    mode: int
    start_local: datetime
    end_local: datetime
    dynamic_start: bool
    dynamic_end: bool
    initial_load_hours: int
    background: bool
    thumb: bool = False


@dataclass(frozen=True)
class RenderMetadata:
    last_update_local: str
    plot_start_local: str
    plot_end_local: str
    flashes_count: int
    events_count: int
    mode: int
    dynamic_start: bool
    dynamic_end: bool
    initial_load_hours: int
    background: bool
    image_time_local: str | None = None
    next_update_local: str | None = None


def _header_value(value: object, *, max_len: int = 320) -> str:
    s = str(value)
    s = s.replace("\r", " ").replace("\n", " ").strip()
    if len(s) > max_len:
        s = s[: max(0, max_len - 3)] + "..."
    return s


def _local_tzinfo() -> tzinfo:
    return datetime.now().astimezone().tzinfo or timezone.utc


def _parse_local_dt(text: str | None, *, base: datetime) -> datetime:
    s = (text or "").strip()
    if not s:
        return base

    # Accept "YYYY-MM-DDTHH:MM:SS" or "YYYY-MM-DD HH:MM:SS"
    s2 = s.replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s2, fmt).replace(tzinfo=base.tzinfo)
        except ValueError:
            pass

    # Accept time-only "HH:MM:SS" or "HH:MM"
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            t = datetime.strptime(s, fmt).time()
            return base.replace(hour=t.hour, minute=t.minute, second=t.second, microsecond=0)
        except ValueError:
            pass

    raise ValueError("Formato inválido de data/hora")


def _to_utc(dt_local: datetime) -> datetime:
    if dt_local.tzinfo is None:
        return dt_local.replace(tzinfo=timezone.utc)
    return dt_local.astimezone(timezone.utc)


def _download_range_with_timeout(
    downloader: GLMDownloader,
    start_utc: datetime,
    end_utc: datetime,
    *,
    interval_seconds: int,
    dest_root: Path,
    timeout_seconds: int,
    logger,
):
    result: dict[str, object] = {"value": None, "error": None}

    def _worker() -> None:
        try:
            result["value"] = downloader.download_range(
                start_utc,
                end_utc,
                interval_seconds=interval_seconds,
                dest_root=dest_root,
            )
        except Exception as exc:
            result["error"] = exc

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    thread.join(timeout=max(1, int(timeout_seconds)))
    if thread.is_alive():
        logger.warning("GLM download timed out after %ss; continuing without S3 fallback", timeout_seconds)
        return None
    if result["error"] is not None:
        logger.warning("GLM download failed: %s", result["error"])
        return None
    return result["value"]


def _set_extent(ax, *, lat0: float, lon0: float, max_radius_km: float) -> tuple[float, float, float, float]:
    dlat = max_radius_km / 111.0
    dlon = max_radius_km / (111.0 * max(0.2, np.cos(np.radians(lat0))))
    lon_min = lon0 - dlon
    lon_max = lon0 + dlon
    lat_min = lat0 - dlat
    lat_max = lat0 + dlat
    ax.set_xlim(lon_min, lon_max)
    ax.set_ylim(lat_min, lat_max)
    ax.set_aspect("equal", adjustable="box")
    return lon_min, lon_max, lat_min, lat_max


_CINZA_JET_CMAP = None


def _cinza_jet_cmap():
    """Colormap for ABI IR: warm temps in gray, cold cloud-tops in jet."""

    global _CINZA_JET_CMAP
    if _CINZA_JET_CMAP is not None:
        return _CINZA_JET_CMAP

    n = 256
    split = int(n * 0.42)  # cold fraction

    jet = plt.get_cmap("jet")
    gray = plt.get_cmap("gray_r")

    cold = jet(np.linspace(0.20, 1.00, split))
    warm = gray(np.linspace(0.00, 1.00, n - split))
    colors = np.vstack([cold, warm])

    _CINZA_JET_CMAP = mcolors.LinearSegmentedColormap.from_list("cinza_jet", colors)
    return _CINZA_JET_CMAP


def _resolve_background_cmap(cmap: str) -> str | Colormap:
    if cmap.strip().lower() == "cinza_jet":
        return _cinza_jet_cmap()
    return cmap


def _choose_time_bin_minutes(duration_minutes: float, *, max_bins: int = 6) -> int:
    if not np.isfinite(duration_minutes) or duration_minutes <= 0:
        return 60

    raw = float(duration_minutes) / float(max(1, int(max_bins)))
    nice = (5, 10, 15, 30, 60, 120, 180, 240, 360, 720, 1440)
    for b in nice:
        if b >= raw:
            return int(b)
    return int(nice[-1])


def _plot_rings(ax, *, lat0: float, lon0: float, radii_km: list[float], label: str):
    palette = ["#d62728", "#ff7f0e", "#2ca02c", "#1f77b4"]

    handles: list[Line2D] = []
    labels: list[str] = []
    for i, r in enumerate(radii_km):
        color = palette[i % len(palette)]
        lats, lons = circle_points(lat0, lon0, r)
        ax.plot(lons, lats, color=color, lw=1.8, zorder=2)
        handles.append(Line2D([0], [0], color=color, lw=2.4))
        labels.append(f"{int(r)} km")

    ax.plot([lon0], [lat0], marker="x", markersize=14, color="black", mew=2.5, zorder=3)

    title = (label or "").strip() or "Tomador de Serviço"
    title = textwrap.fill(title, width=28)

    return handles, labels, title


@lru_cache(maxsize=1)
def _load_state_boundaries():
    if geobr is None or gpd is None:
        return None
    try:
        return geobr.read_state(year=2020).to_crs(4326)
    except Exception:
        return None


@lru_cache(maxsize=1)
def _load_municipality_boundaries():
    if geobr is None or gpd is None:
        return None
    try:
        return geobr.read_municipality(year=2020).to_crs(4326)
    except Exception:
        return None


def _plot_admin_shapes(ax, *, lat0: float, lon0: float) -> None:
    if geobr is None or gpd is None:
        return

    states = _load_state_boundaries()
    municipalities = _load_municipality_boundaries()
    if states is None or states.empty or municipalities is None or municipalities.empty:
        return

    point = gpd.GeoDataFrame(geometry=gpd.points_from_xy([lon0], [lat0]), crs="EPSG:4326")

    try:
        state_join = gpd.sjoin(point, states, how="left", predicate="within")
    except Exception:
        state_join = gpd.sjoin(point, states, how="left", predicate="intersects")

    if state_join.empty or "index_right" not in state_join.columns:
        return

    state_idx = state_join.iloc[0].get("index_right")
    if pd.isna(state_idx):
        return

    try:
        state_geom = states.loc[int(state_idx)].geometry
    except Exception:
        state_geom = None

    muni_pool = municipalities
    state_code = None
    if state_idx is not None:
        try:
            state_row = states.loc[int(state_idx)]
            state_code = state_row.get("code_state")
        except Exception:
            state_code = None

    if state_code is not None and "code_state" in municipalities.columns:
        muni_pool = municipalities[municipalities["code_state"] == state_code]
        if muni_pool.empty:
            muni_pool = municipalities

    try:
        muni_join = gpd.sjoin(point, muni_pool, how="left", predicate="within")
    except Exception:
        muni_join = gpd.sjoin(point, muni_pool, how="left", predicate="intersects")

    muni_geom = None
    if not muni_join.empty and "index_right" in muni_join.columns:
        muni_idx = muni_join.iloc[0].get("index_right")
        if not pd.isna(muni_idx):
            try:
                muni_geom = muni_pool.loc[int(muni_idx)].geometry
            except Exception:
                muni_geom = None

    if state_geom is not None:
        gpd.GeoSeries([state_geom], crs="EPSG:4326").plot(
            ax=ax,
            facecolor=(1.0, 1.0, 1.0, 0.08),
            edgecolor="#ffffff",
            linewidth=1.8,
            zorder=1.15,
        )

    if muni_geom is not None:
        gpd.GeoSeries([muni_geom], crs="EPSG:4326").plot(
            ax=ax,
            facecolor="none",
            edgecolor="#000000",
            linewidth=1.4,
            zorder=1.25,
        )


def _load_logo_image() -> np.ndarray | None:
    logo_path = Path(__file__).resolve().parents[1] / "logo.png"
    if not logo_path.exists():
        return None
    try:
        return plt.imread(str(logo_path))
    except Exception:
        return None


def _add_logo(fig, *, thumb: bool, ax=None) -> None:
    logo = _load_logo_image()
    if logo is None:
        return

    # Try to place the logo inside the axes (so it becomes part of the image)
    # using axes fraction coordinates. If that fails, fall back to figure-based
    # inset so behavior is backwards-compatible.
    try:
        if ax is not None:
            zoom = 0.04 if thumb else 0.07
            image = OffsetImage(logo, zoom=zoom)
            artist = AnnotationBbox(
                image,
                (0.02, 0.02),
                xycoords=ax.transAxes,
                box_alignment=(0.0, 0.0),
                frameon=False,
                pad=0.0,
                zorder=30,
            )
            ax.add_artist(artist)
            return
    except Exception:
        pass

    # Fallback: Place the logo in a small inset axes in figure coordinates so it cannot
    # overflow or cover the central plot. Use a conservative fraction size.
    try:
        frac = 0.06 if thumb else 0.10
        left = 0.015
        bottom = 0.015
        width = frac
        height = frac * (logo.shape[0] / logo.shape[1]) if logo.shape[1] != 0 else frac
        ax_logo = fig.add_axes([left, bottom, width, height], anchor="SW", zorder=25)
        ax_logo.imshow(logo)
        ax_logo.axis("off")
    except Exception:
        try:
            zoom = 0.04 if thumb else 0.07
            image = OffsetImage(logo, zoom=zoom)
            artist = AnnotationBbox(
                image,
                (0.02, 0.02),
                xycoords="figure fraction",
                box_alignment=(0.0, 0.0),
                frameon=False,
                pad=0.0,
                zorder=20,
            )
            fig.add_artist(artist)
        except Exception:
            return


def _draw_polygon(ax, *, lon: np.ndarray, lat: np.ndarray) -> None:
    if lon.size < 3:
        return
    pts = list(zip(lon.tolist(), lat.tolist()))
    hull = convex_hull_lonlat(pts)
    if len(hull) < 3:
        return
    poly = Polygon(hull, closed=True, facecolor="#b3b3b3", edgecolor="none", alpha=0.45)
    ax.add_patch(poly)


def _plot_density(ax, df: pd.DataFrame) -> None:
    if df.empty:
        return
    x = df["lon"].to_numpy()
    y = df["lat"].to_numpy()
    xmin, xmax = ax.get_xlim()
    ymin, ymax = ax.get_ylim()

    bins = 220
    H, xedges, yedges = np.histogram2d(x, y, bins=bins, range=[[xmin, xmax], [ymin, ymax]])
    H = H.T

    try:
        from scipy.ndimage import gaussian_filter  # type: ignore

        H = gaussian_filter(H, sigma=2.0)
    except Exception:
        pass

    img = ax.imshow(H, extent=[xmin, xmax, ymin, ymax], origin="lower", cmap="hot", alpha=0.75, aspect="auto")
    return img


def render_png(
    *,
    settings_path: Path,
    params: RenderParams,
) -> tuple[bytes, RenderMetadata, dict[str, str]]:
    render_started = time.perf_counter()
    stage_started = render_started
    stage_timings: dict[str, float] = {}

    def mark_stage(name: str) -> None:
        nonlocal stage_started
        now = time.perf_counter()
        stage_ms = (now - stage_started) * 1000.0
        stage_timings[name] = stage_ms
        sys.stderr.write(f"X-Render-Stage-{name.replace('_', '-')}-Ms: {stage_ms:.0f}\n")
        sys.stderr.flush()
        stage_started = now

    settings = load_settings(settings_path)
    mark_stage("settings")

    # Determine plotting window.
    now_local = datetime.now().astimezone(params.start_local.tzinfo)
    plot_start = params.start_local
    plot_end = params.end_local
    if params.dynamic_start:
        plot_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    if params.dynamic_end:
        plot_end = now_local
    if plot_end < plot_start:
        plot_end = plot_start
    mark_stage("window")

    lag = timedelta(seconds=int(settings.aws_availability_lag_sec))
    effective_now_utc = datetime.now(timezone.utc) - lag

    end_utc = min(_to_utc(plot_end), effective_now_utc)
    start_utc = _to_utc(plot_start)

    # Initial-load optimization: when start is dynamic (00:00) we can start downloading only the last N hours
    # but never earlier than midnight local.
    fetch_start_utc = start_utc
    init_hours = max(0, int(params.initial_load_hours))
    init_hours = min(init_hours, int(settings.history_hours))
    if params.dynamic_start and init_hours > 0:
        midnight_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        midnight_utc = midnight_local.astimezone(timezone.utc)
        fetch_start_utc = max(end_utc - timedelta(hours=init_hours), midnight_utc)
    elif params.dynamic_start:
        # Default dynamic renders should stay lightweight; use roughly one GLM interval instead of
        # downloading several minutes of files when the user left Carga inicial at zero.
        default_load_seconds = max(20, int(settings.aws_interval_seconds))
        midnight_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        midnight_utc = midnight_local.astimezone(timezone.utc)
        fetch_start_utc = max(end_utc - timedelta(seconds=default_load_seconds), midnight_utc)
    mark_stage("fetch_window")

    downloader = GLMDownloader(bucket=settings.aws_bucket, product_prefix=settings.aws_product_prefix, goes_number=19)

    dsn = get_postgres_dsn()
    flashes: list[pd.DataFrame] = []
    events: list[pd.DataFrame] = []
    data_source = "S3 fallback"
    need_events = True
    events_full_history = params.mode in (3, 4)
    if need_events and not events_full_history:
        events_extract_start_utc = max(fetch_start_utc, end_utc - timedelta(minutes=int(settings.plot_polygon_events_window_minutes)))
    else:
        events_extract_start_utc = fetch_start_utc

    if dsn:
        try:
            flashes_df_db = load_points_from_postgres(dsn=dsn, kind="flash", start_utc=fetch_start_utc, end_utc=end_utc)
            if not flashes_df_db.empty:
                flashes.append(flashes_df_db)

            if need_events:
                events_df_db = load_points_from_postgres(dsn=dsn, kind="event", start_utc=events_extract_start_utc, end_utc=end_utc)
                if not events_df_db.empty:
                    events.append(events_df_db)
            if flashes or events:
                data_source = "Postgres"
        except Exception:
            # DB is optional; fall back to the existing download path.
            flashes = []
            events = []
            data_source = "S3 fallback"
    mark_stage("postgres")

    if not flashes:
        fallback_started = time.perf_counter()
        dl = _download_range_with_timeout(
            downloader,
            fetch_start_utc,
            end_utc,
            interval_seconds=settings.aws_interval_seconds,
            dest_root=settings.raw_dir,
            timeout_seconds=int(settings.fetch_timeout_seconds),
            logger=logging.getLogger(__name__),
        )
        data_source = "S3 fallback"
        stage_timings["fallback_download"] = (time.perf_counter() - fallback_started) * 1000.0

        if dl is None:
            dl = type("DownloadResult", (), {"downloaded": [], "not_found": []})()

        extract_started = time.perf_counter()
        for p in dl.downloaded:
            try:
                fdf = extract_points_from_lcfa(p, kind="flash").df
                flashes.append(fdf)

                if need_events:
                    edf = extract_points_from_lcfa(p, kind="event").df
                    if not edf.empty:
                        edf = edf[edf["time"] >= events_extract_start_utc]
                    events.append(edf)
            except Exception:
                continue
        stage_timings["fallback_extract"] = (time.perf_counter() - extract_started) * 1000.0
    mark_stage("data_load")

    flashes_df = pd.concat(flashes, ignore_index=True) if flashes else pd.DataFrame(columns=["time", "lat", "lon"])
    events_df = pd.concat(events, ignore_index=True) if events else pd.DataFrame(columns=["time", "lat", "lon"])

    # Filter to max radius for perf.
    max_r = float(max(settings.radii_km))
    if not flashes_df.empty:
        dist = haversine_km(params.lat0, params.lon0, flashes_df["lat"].to_numpy(), flashes_df["lon"].to_numpy())
        flashes_df = flashes_df[dist <= max_r].copy()

    if not events_df.empty:
        dist = haversine_km(params.lat0, params.lon0, events_df["lat"].to_numpy(), events_df["lon"].to_numpy())
        events_df = events_df[dist <= max_r].copy()

    # Time filter for plot.
    tloc_f = flashes_df["time"].dt.tz_convert(plot_start.tzinfo) if not flashes_df.empty else None
    if tloc_f is not None:
        flashes_df = flashes_df[(tloc_f >= plot_start) & (tloc_f <= plot_end)]

    if len(flashes_df) > int(settings.plot_max_points):
        flashes_df = flashes_df.sample(int(settings.plot_max_points), random_state=0)

    tloc_e = events_df["time"].dt.tz_convert(plot_start.tzinfo) if not events_df.empty else None
    if tloc_e is not None:
        events_df = events_df[(tloc_e >= plot_start) & (tloc_e <= plot_end)]

    if len(events_df) > int(settings.plot_max_points):
        events_df = events_df.sample(int(settings.plot_max_points), random_state=0)
    mark_stage("filter")

    # Background overlay.
    bg_headers: dict[str, str] = {}
    bg_headers["X-Background-Settings-Enabled"] = str(int(settings.background_enabled))
    bg: BackgroundImage | None = None
    if params.background:
        bg_diag: dict[str, str] = {}
        try:
            provider = AbiIrBackgroundProvider(
                bucket=settings.background_bucket,
                product_prefix=settings.background_product_prefix,
                channel=settings.background_channel,
                cache_dir=settings.background_cache_dir,
                alpha=settings.background_alpha,
                cmap=settings.background_cmap,
                vmin_k=settings.background_vmin_k,
                vmax_k=settings.background_vmax_k,
                max_dim=settings.background_max_dim,
            )
            fig_tmp, ax_tmp = plt.subplots(figsize=(8, 8), dpi=settings.plot_dpi)
            lon_min, lon_max, lat_min, lat_max = _set_extent(ax_tmp, lat0=params.lat0, lon0=params.lon0, max_radius_km=max_r)
            plt.close(fig_tmp)
            # Fetch background in a daemon worker so a slow network/S3 call cannot block rendering.
            bg_result: dict[str, object] = {"value": None, "error": None}

            def _load_background() -> None:
                try:
                    bg_result["value"] = provider.get_background(
                        dt_utc=end_utc,
                        extent=(lon_min, lon_max, lat_min, lat_max),
                        diag=bg_diag,
                    )
                except Exception as e:
                    bg_result["error"] = e

            worker = threading.Thread(target=_load_background, daemon=True)
            worker.start()
            worker.join(timeout=max(1, int(settings.background_fetch_timeout_seconds)))

            if worker.is_alive():
                bg = None
                bg_diag.setdefault("reason", "background_timeout")
                bg_diag.setdefault("detail", f"background fetch timed out after {int(settings.background_fetch_timeout_seconds)}s")
            elif bg_result["error"] is not None:
                bg = None
                e = bg_result["error"]
                bg_diag.setdefault("reason", "exception")
                bg_diag.setdefault("detail", f"{type(e).__name__}: {e}")
            else:
                bg = cast(BackgroundImage | None, bg_result["value"])
        except Exception as e:
            bg = None

            # Keep short, safe error text for HTTP headers.
            bg_diag.setdefault("reason", "exception")
            bg_diag.setdefault("detail", f"{type(e).__name__}: {e}")

        bg_headers["X-Background-Applied"] = str(int(bg is not None))
        bg_headers["X-Background-Reason"] = str(bg_diag.get("reason") or ("ok" if bg is not None else "unknown"))

        mapping = {
            "detail": "X-Background-Detail",
            "warning": "X-Background-Warning",
            "netcdf_open_path_kind": "X-Background-NetCDF-Path-Kind",
            "netcdf_open_path": "X-Background-NetCDF-Path",
            "dt_utc": "X-Background-Dt-UTC",
            "extent": "X-Background-Extent",
            "bucket": "X-Background-S3-Bucket",
            "product_prefix": "X-Background-S3-Product",
            "channel": "X-Background-S3-Channel",
            "prefix0": "X-Background-S3-Prefix0",
            "prefix1": "X-Background-S3-Prefix1",
            "s3_key": "X-Background-S3-Key",
            "file_time_utc": "X-Background-File-Time-UTC",
            "local_file": "X-Background-File",
            "cache": "X-Background-Cache",
            "subset_origin": "X-Background-Subset-Origin",
            "subset_shape": "X-Background-Subset-Shape",
            "subset_step": "X-Background-Subset-Step",
            "subset_finite": "X-Background-Subset-Finite",
        }
        for diag_key, header_key in mapping.items():
            v = bg_diag.get(diag_key)
            if v:
                bg_headers[header_key] = str(v)
        bg_headers["X-Background-Fetch-Timeout-Sec"] = str(int(settings.background_fetch_timeout_seconds))
    else:
        bg_headers["X-Background-Applied"] = "0"
        bg_headers["X-Background-Reason"] = "not_requested"
    mark_stage("background")

    # Render figure.
    figsize = (6.6, 5.6) if params.thumb else (8.4, 7.2)
    dpi = 96 if params.thumb else settings.plot_dpi
    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    # Make axes occupy nearly the full figure so the image fills the PNG.
    fig.patch.set_facecolor("white")
    fig.subplots_adjust(left=0.005, right=0.995, top=0.995, bottom=0.005)
    lon_min, lon_max, lat_min, lat_max = _set_extent(ax, lat0=params.lat0, lon0=params.lon0, max_radius_km=max_r)
    
    # Track background composition for diagnostics
    bg_imshow_executed = 0
    if bg is not None:
        bg_imshow_executed = 1
        bg_img = ax.imshow(
            bg.data,
            extent=bg.extent,
            origin=bg.origin,
            cmap=_resolve_background_cmap(bg.cmap),
            alpha=float(bg.alpha),
            vmin=bg.vmin,
            vmax=bg.vmax,
            zorder=0,
            aspect="auto",
        )
    bg_headers["X-Debug-BG-Imshow-Executed"] = str(bg_imshow_executed)

    if settings.plot_show_admin_shapes:
        _plot_admin_shapes(ax, lat0=params.lat0, lon0=params.lon0)

    ring_handles, ring_labels, ring_title = _plot_rings(
        ax,
        lat0=params.lat0,
        lon0=params.lon0,
        radii_km=settings.radii_km,
        label=params.taker_name,
    )
    if ring_handles:
        # Place the ring legend inside the axes (axes fraction coords)
        rings_leg = ax.legend(
            ring_handles,
            ring_labels,
            loc="upper left",
            bbox_to_anchor=(0.02, 0.96),
            bbox_transform=ax.transAxes,
            frameon=False,
            fontsize=9 if params.thumb else 10,
            title=ring_title,
        )
        try:
            legend_box = getattr(rings_leg, "_legend_box", None)
            if legend_box is not None:
                legend_box.align = "left"
        except Exception:
            pass

    # Polygon from events when available.
    poly_df = events_df if not events_df.empty else flashes_df
    if poly_df is not None and not poly_df.empty:
        _draw_polygon(ax, lon=poly_df["lon"].to_numpy(), lat=poly_df["lat"].to_numpy())

    if params.mode == 1:
        if not flashes_df.empty:
            t_local = flashes_df["time"].dt.tz_convert(plot_start.tzinfo)
            duration_minutes = max(1.0, (plot_end - plot_start).total_seconds() / 60.0)
            # Use 30-minute bins to keep the time legend readable without overcrowding.
            bin_minutes = 30
            n_bins = max(1, int(np.ceil(duration_minutes / float(bin_minutes))))

            x = flashes_df["lon"].to_numpy()
            y = flashes_df["lat"].to_numpy()
            secs = (t_local - plot_start).dt.total_seconds().to_numpy().astype(np.float64, copy=False)
            idx = np.floor(secs / float(bin_minutes * 60)).astype(int)
            idx = np.clip(idx, 0, n_bins - 1)

            cmap = plt.get_cmap("jet")
            colors = [cmap(v) for v in np.linspace(0.15, 0.95, n_bins)]

            time_handles: list[Line2D] = []
            time_labels: list[str] = []
            for i in range(n_bins):
                mask = idx == i
                if not np.any(mask):
                    continue

                ax.scatter(x[mask], y[mask], s=36, color=colors[i], edgecolors="none", zorder=4)

                bin_start = plot_start + timedelta(minutes=i * bin_minutes)
                bin_end = min(plot_start + timedelta(minutes=(i + 1) * bin_minutes), plot_end)
                time_handles.append(
                    Line2D(
                        [0],
                        [0],
                        marker="o",
                        linestyle="none",
                        markerfacecolor=colors[i],
                        markeredgecolor="none",
                        markersize=8,
                    )
                )
                time_labels.append(f"{bin_start:%H:%M}–{bin_end:%H:%M}")

            if time_handles:
                # Place the time legend inside the axes so it is part of the image
                time_leg = ax.legend(
                    time_handles,
                    time_labels,
                    loc="upper right",
                    bbox_to_anchor=(0.98, 0.96),
                    bbox_transform=ax.transAxes,
                    frameon=False,
                    fontsize=7 if params.thumb else 8,
                    title="Tempo (local)",
                )
                try:
                    legend_box = getattr(time_leg, "_legend_box", None)
                    if legend_box is not None:
                        legend_box.align = "left"
                except Exception:
                    pass
    elif params.mode == 2:
        density_img = _plot_density(ax, flashes_df)
    elif params.mode == 3:
        if not events_df.empty:
            ax.scatter(events_df["lon"].to_numpy(), events_df["lat"].to_numpy(), s=22, c="#7f7f7f", edgecolors="none")
    elif params.mode == 4:
        density_img = _plot_density(ax, events_df)

    _add_logo(fig, thumb=params.thumb, ax=ax)

    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_frame_on(False)
    ax.set_facecolor("white")

    # Overlay small metadata text: image time and next update (local)
    try:
        now_local = datetime.now().astimezone(plot_start.tzinfo)
        # Ceil to next 5-minute boundary
        minute = now_local.minute
        next_minute = ((minute // 5) + 1) * 5
        next_dt = now_local.replace(second=0, microsecond=0)
        if next_minute >= 60:
            next_dt = next_dt.replace(hour=(now_local.hour + 1) % 24, minute=0) + timedelta(days=1) if now_local.hour == 23 and next_minute >= 60 else next_dt.replace(minute=0, hour=(now_local.hour + 1) % 24)
        else:
            next_dt = next_dt.replace(minute=next_minute)

        image_time_local = end_utc.astimezone(plot_start.tzinfo).strftime("%Y-%m-%d %H:%M:%S")
        next_update_local = next_dt.strftime("%Y-%m-%d %H:%M:%S")

        txt = f"Imagem: {image_time_local}  |  Próx. atualização: {next_update_local}"
        ax.text(0.99, 0.01, txt, ha="right", va="bottom", transform=ax.transAxes, fontsize=9, color="#111", bbox=dict(facecolor="white", alpha=0.6, edgecolor="none"))
    except Exception:
        image_time_local = None
        next_update_local = None

    buf = BytesIO()
    # Save without extra padding so the PNG contains the full axes content.
    fig.savefig(buf, format="png", bbox_inches="tight", pad_inches=0)
    plt.close(fig)
    mark_stage("plot_save")

    png = buf.getvalue()
    total_ms = (time.perf_counter() - render_started) * 1000.0
    timing_parts = [f"total={total_ms:.0f}ms"]
    for key in ("settings", "window", "fetch_window", "postgres", "fallback_download", "fallback_extract", "data_load", "filter", "background", "plot_save"):
        value = stage_timings.get(key)
        if value is not None:
            timing_parts.append(f"{key}={value:.0f}ms")
    bg_headers["X-Render-Timings"] = ";".join(timing_parts)
    last_update_local = plot_end.strftime("%H:%M:%S")
    metadata = RenderMetadata(
        last_update_local=last_update_local,
        plot_start_local=plot_start.strftime("%Y-%m-%d %H:%M:%S"),
        plot_end_local=plot_end.strftime("%Y-%m-%d %H:%M:%S"),
        flashes_count=int(len(flashes_df)),
        events_count=int(len(events_df)),
        mode=int(params.mode),
        dynamic_start=bool(params.dynamic_start),
        dynamic_end=bool(params.dynamic_end),
        initial_load_hours=int(params.initial_load_hours),
        background=bool(params.background),
        image_time_local=image_time_local,
        next_update_local=next_update_local,
    )
    bg_headers["X-Data-Source"] = data_source
    return png, metadata, bg_headers


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Render map PNG for Lightning Tracker web backend")

    p.add_argument("--settings", default=str(Path("config/settings.yaml")), help="Path to settings.yaml")

    p.add_argument("--name", required=True, help="Taker name")
    p.add_argument("--lat", required=True, type=float, help="Taker latitude")
    p.add_argument("--lon", required=True, type=float, help="Taker longitude")

    p.add_argument("--mode", type=int, default=1, choices=[1, 2, 3, 4])

    p.add_argument("--start-local", default="", help="Start local (YYYY-MM-DDTHH:MM:SS) or empty")
    p.add_argument("--end-local", default="", help="End local (YYYY-MM-DDTHH:MM:SS) or empty")

    p.add_argument("--initial-load-hours", type=int, default=0, help="Initial load hours optimization")
    p.add_argument("--background", type=int, default=0, help="1 to enable background overlay (if configured)")
    p.add_argument("--thumb", type=int, default=0, choices=[0, 1], help="1 to render a smaller thumbnail frame")

    return p


def main() -> int:
    args = _build_arg_parser().parse_args()

    tz = _local_tzinfo()
    now = datetime.now().astimezone(tz)
    base_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    dynamic_start = (args.start_local or "").strip() == ""
    dynamic_end = (args.end_local or "").strip() == ""

    start_local = _parse_local_dt(args.start_local, base=base_start)
    end_local = _parse_local_dt(args.end_local, base=now)
    if end_local < start_local:
        start_local, end_local = end_local, start_local

    params = RenderParams(
        taker_name=str(args.name),
        lat0=float(args.lat),
        lon0=float(args.lon),
        mode=int(args.mode),
        start_local=start_local,
        end_local=end_local,
        dynamic_start=dynamic_start,
        dynamic_end=dynamic_end,
        initial_load_hours=int(args.initial_load_hours),
        background=bool(int(args.background)),
        thumb=bool(int(args.thumb)),
    )

    settings_path = Path(str(args.settings))
    png, metadata, extra_headers = render_png(settings_path=settings_path, params=params)

    # Protocol: stderr carries key/value metadata headers; stdout = raw PNG bytes.
    sys.stderr.write(f"X-Last-Update-Local: {metadata.last_update_local}\n")
    sys.stderr.write(f"X-Plot-Start-Local: {metadata.plot_start_local}\n")
    sys.stderr.write(f"X-Plot-End-Local: {metadata.plot_end_local}\n")
    if metadata.image_time_local:
        sys.stderr.write(f"X-Image-Time-Local: {metadata.image_time_local}\n")
    if metadata.next_update_local:
        sys.stderr.write(f"X-Next-Update-Local: {metadata.next_update_local}\n")
    sys.stderr.write(f"X-Flashes-Count: {metadata.flashes_count}\n")
    sys.stderr.write(f"X-Events-Count: {metadata.events_count}\n")
    sys.stderr.write(f"X-Mode: {metadata.mode}\n")
    sys.stderr.write(f"X-Dynamic-Start: {int(metadata.dynamic_start)}\n")
    sys.stderr.write(f"X-Dynamic-End: {int(metadata.dynamic_end)}\n")
    sys.stderr.write(f"X-Initial-Load-Hours: {metadata.initial_load_hours}\n")
    sys.stderr.write(f"X-Background: {int(metadata.background)}\n")
    if extra_headers.get("X-Data-Source"):
        sys.stderr.write(f"X-Data-Source: {extra_headers['X-Data-Source']}\n")

    for k, v in (extra_headers or {}).items():
        if not k.startswith("X-"):
            continue
        vv = _header_value(v)
        if vv:
            sys.stderr.write(f"{k}: {vv}\n")
    sys.stderr.flush()

    sys.stdout.buffer.write(png)
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
