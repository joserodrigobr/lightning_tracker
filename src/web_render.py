from __future__ import annotations

import argparse
import os
import sys
import textwrap
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd

# Force headless rendering for web/server usage.
os.environ.setdefault("MPLBACKEND", "Agg")

import matplotlib
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
from matplotlib.colors import Colormap
from matplotlib.lines import Line2D
from matplotlib.patches import Polygon

from .background import AbiIrBackgroundProvider
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


def _set_extent(ax, *, lat0: float, lon0: float, max_radius_km: float) -> tuple[float, float, float, float]:
    dlat = max_radius_km / 111.0
    dlon = max_radius_km / (111.0 * max(0.2, np.cos(np.radians(lat0))))
    pad = 0.15
    lon_min = lon0 - dlon * (1 + pad)
    lon_max = lon0 + dlon * (1 + pad)
    lat_min = lat0 - dlat * (1 + pad)
    lat_max = lat0 + dlat * (1 + pad)
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

    leg = ax.legend(handles, labels, loc="upper left", frameon=True, fontsize=10)
    try:
        leg.set_title(title)
    except Exception:
        pass
    try:
        frame = leg.get_frame()
        frame.set_alpha(0.75)
    except Exception:
        pass
    return leg


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

    ax.imshow(H, extent=[xmin, xmax, ymin, ymax], origin="lower", cmap="hot", alpha=0.75, aspect="auto")


def render_png(
    *,
    settings_path: Path,
    params: RenderParams,
) -> tuple[bytes, RenderMetadata, dict[str, str]]:
    settings = load_settings(settings_path)

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

    downloader = GLMDownloader(bucket=settings.aws_bucket, product_prefix=settings.aws_product_prefix, goes_number=19)

    dl = downloader.download_range(fetch_start_utc, end_utc, interval_seconds=settings.aws_interval_seconds, dest_root=settings.raw_dir)

    flashes = []
    events = []

    need_events = True
    events_full_history = params.mode in (3, 4)
    if need_events and not events_full_history:
        events_extract_start_utc = max(fetch_start_utc, end_utc - timedelta(minutes=int(settings.plot_polygon_events_window_minutes)))
    else:
        events_extract_start_utc = fetch_start_utc

    for p in dl.downloaded:
        try:
            fdf = extract_points_from_lcfa(p, kind="flash").df
            flashes.append(fdf)

            if need_events:
                # Only parse recent event files when used just for polygon overlay.
                if events_full_history:
                    do_events = True
                else:
                    # Compare by file mtime as a cheap proxy; if in doubt parse.
                    do_events = True

                if do_events:
                    edf = extract_points_from_lcfa(p, kind="event").df
                    if not edf.empty:
                        edf = edf[edf["time"] >= events_extract_start_utc]
                    events.append(edf)
        except Exception:
            continue

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

    # Background overlay.
    bg_headers: dict[str, str] = {}
    bg_headers["X-Background-Settings-Enabled"] = str(int(settings.background_enabled))
    bg = None
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
            bg = provider.get_background(dt_utc=end_utc, extent=(lon_min, lon_max, lat_min, lat_max), diag=bg_diag)
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
    else:
        bg_headers["X-Background-Applied"] = "0"
        bg_headers["X-Background-Reason"] = "not_requested"

    # Render figure.
    fig, ax = plt.subplots(figsize=(8.4, 7.2), dpi=settings.plot_dpi)
    lon_min, lon_max, lat_min, lat_max = _set_extent(ax, lat0=params.lat0, lon0=params.lon0, max_radius_km=max_r)

    if bg is not None:
        ax.imshow(
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

    rings_leg = _plot_rings(ax, lat0=params.lat0, lon0=params.lon0, radii_km=settings.radii_km, label=params.taker_name)
    if rings_leg is not None:
        ax.add_artist(rings_leg)

    # Polygon from events when available.
    poly_df = events_df if not events_df.empty else flashes_df
    if poly_df is not None and not poly_df.empty:
        _draw_polygon(ax, lon=poly_df["lon"].to_numpy(), lat=poly_df["lat"].to_numpy())

    if params.mode == 1:
        if not flashes_df.empty:
            t_local = flashes_df["time"].dt.tz_convert(plot_start.tzinfo)
            duration_minutes = max(1.0, (plot_end - plot_start).total_seconds() / 60.0)
            bin_minutes = _choose_time_bin_minutes(duration_minutes, max_bins=6)
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
                time_leg = ax.legend(time_handles, time_labels, loc="lower left", frameon=True, fontsize=9, title="Tempo (local)")
                try:
                    frame = time_leg.get_frame()
                    frame.set_alpha(0.75)
                except Exception:
                    pass
    elif params.mode == 2:
        _plot_density(ax, flashes_df)
    elif params.mode == 3:
        if not events_df.empty:
            ax.scatter(events_df["lon"].to_numpy(), events_df["lat"].to_numpy(), s=22, c="#7f7f7f", edgecolors="none")
    elif params.mode == 4:
        _plot_density(ax, events_df)

    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_linewidth(1.5)
        spine.set_color("#111")

    fig.tight_layout()

    buf = BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)

    png = buf.getvalue()
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
    )
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
    )

    settings_path = Path(str(args.settings))
    png, metadata, extra_headers = render_png(settings_path=settings_path, params=params)

    # Protocol: stderr carries key/value metadata headers; stdout = raw PNG bytes.
    sys.stderr.write(f"X-Last-Update-Local: {metadata.last_update_local}\n")
    sys.stderr.write(f"X-Plot-Start-Local: {metadata.plot_start_local}\n")
    sys.stderr.write(f"X-Plot-End-Local: {metadata.plot_end_local}\n")
    sys.stderr.write(f"X-Flashes-Count: {metadata.flashes_count}\n")
    sys.stderr.write(f"X-Events-Count: {metadata.events_count}\n")
    sys.stderr.write(f"X-Mode: {metadata.mode}\n")
    sys.stderr.write(f"X-Dynamic-Start: {int(metadata.dynamic_start)}\n")
    sys.stderr.write(f"X-Dynamic-End: {int(metadata.dynamic_end)}\n")
    sys.stderr.write(f"X-Initial-Load-Hours: {metadata.initial_load_hours}\n")
    sys.stderr.write(f"X-Background: {int(metadata.background)}\n")

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
