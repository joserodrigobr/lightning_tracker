from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

import matplotlib
import matplotlib.colors as mcolors
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.colors import Colormap
from matplotlib.patches import Polygon

from .geo import circle_points, convex_hull_lonlat
from .background import BackgroundImage


_CINZA_JET_CMAP = None


def _cinza_jet_cmap():
    """Colormap for ABI IR: warm temps in gray, cold cloud-tops in jet."""

    global _CINZA_JET_CMAP
    if _CINZA_JET_CMAP is not None:
        return _CINZA_JET_CMAP

    n = 256
    split = int(n * 0.42)

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


@dataclass(frozen=True)
class TableRender:
    values_4x24: np.ndarray
    hour_labels: list[str]
    radii_labels: list[str]


class Visualizer:
    def __init__(self, *, radii_km: list[float], max_points: int = 30000, dpi: int = 120, show_polygon: bool = True):
        self.radii_km = radii_km
        self.max_points = max_points
        self.dpi = dpi
        self.show_polygon = show_polygon

        self.fig = plt.figure(figsize=(12, 7), dpi=dpi)
        gs = self.fig.add_gridspec(1, 2, width_ratios=[1.25, 1.0])
        self.ax = self.fig.add_subplot(gs[0, 0])
        self.ax_table = self.fig.add_subplot(gs[0, 1])
        try:
            manager = getattr(self.fig.canvas, "manager", None)
            if manager is not None and hasattr(manager, "set_window_title"):
                manager.set_window_title("Monitoramento de Raios")
        except Exception:
            pass
        self._cbar = None

        # Try to show a GUI window when a GUI backend is available.
        try:
            plt.show(block=False)
        except Exception:
            pass

    def clear(self) -> None:
        self.ax.clear()
        self.ax_table.clear()
        if self._cbar is not None:
            try:
                self._cbar.remove()
            except Exception:
                pass
            self._cbar = None

    def _set_extent(self, lat0: float, lon0: float, max_radius_km: float) -> None:
        # Rough degree conversion with latitude correction
        dlat = max_radius_km / 111.0
        dlon = max_radius_km / (111.0 * max(0.2, np.cos(np.radians(lat0))))
        pad = 0.15
        self.ax.set_xlim(lon0 - dlon * (1 + pad), lon0 + dlon * (1 + pad))
        self.ax.set_ylim(lat0 - dlat * (1 + pad), lat0 + dlat * (1 + pad))
        self.ax.set_aspect("equal", adjustable="box")

    def _plot_rings(self, lat0: float, lon0: float, alert_ring_idx: set[int] | None = None) -> None:
        alert_ring_idx = alert_ring_idx or set()
        for i, r in enumerate(self.radii_km):
            lats, lons = circle_points(lat0, lon0, r)
            color = "#cc0000" if i in alert_ring_idx else "#00324d"
            lw = 2.5 if i in alert_ring_idx else 1.6
            self.ax.plot(lons, lats, color=color, lw=lw)
            # label on left
            self.ax.text(lon0 - (r / 111.0) * 0.92, lat0 + (r / 111.0) * 0.05, f"{int(r)}km", fontsize=11)

        self.ax.plot([lon0], [lat0], marker="x", markersize=12, color="black", mew=2)

    def _draw_polygon(self, lon: np.ndarray, lat: np.ndarray) -> None:
        if not self.show_polygon:
            return
        if lon.size < 3:
            return
        pts = list(zip(lon.tolist(), lat.tolist()))
        hull = convex_hull_lonlat(pts)
        if len(hull) < 3:
            return
        poly = Polygon(hull, closed=True, facecolor="#b3b3b3", edgecolor="none", alpha=0.45)
        self.ax.add_patch(poly)

    def _plot_scatter_timecolored(self, df: pd.DataFrame, *, start_local: datetime, end_local: datetime) -> None:
        if df.empty:
            return
        df = df.copy()
        # Convert to local for colormap
        t_local = df["time"].dt.tz_convert(start_local.tzinfo)
        t_num = mdates.date2num(t_local.dt.to_pydatetime())
        norm = mcolors.Normalize(vmin=float(mdates.date2num(start_local)), vmax=float(mdates.date2num(end_local)))

        sc = self.ax.scatter(df["lon"].to_numpy(), df["lat"].to_numpy(), c=t_num, s=32, cmap="jet", norm=norm, edgecolors="none")
        self._cbar = self.fig.colorbar(sc, ax=self.ax, orientation="horizontal", pad=0.08, fraction=0.06)
        self._cbar.set_label("Tempo (hora local)")

    def _plot_density(self, df: pd.DataFrame) -> None:
        if df.empty:
            return
        x = df["lon"].to_numpy()
        y = df["lat"].to_numpy()
        xmin, xmax = self.ax.get_xlim()
        ymin, ymax = self.ax.get_ylim()

        # Fallback density: 2D histogram
        bins = 220
        H, xedges, yedges = np.histogram2d(x, y, bins=bins, range=[[xmin, xmax], [ymin, ymax]])
        H = H.T

        try:
            from scipy.ndimage import gaussian_filter  # type: ignore

            H = gaussian_filter(H, sigma=2.0)
        except Exception:
            pass

        self.ax.imshow(
            H,
            extent=(xmin, xmax, ymin, ymax),
            origin="lower",
            cmap="hot",
            alpha=0.75,
            aspect="auto",
        )

    def _render_table(self, table: TableRender) -> None:
        self.ax_table.axis("off")
        # Render as a matplotlib table
        cell_text = [[str(int(v)) for v in row] for row in table.values_4x24]
        t = self.ax_table.table(
            cellText=cell_text,
            rowLabels=table.radii_labels,
            colLabels=table.hour_labels,
            loc="center",
            cellLoc="center",
            rowLoc="center",
        )
        t.auto_set_font_size(False)
        t.set_fontsize(8)
        t.scale(1.0, 1.25)
        self.ax_table.set_title("Flashes por hora × anel", fontsize=12, pad=12)

    def update(self, *, taker_name: str, lat0: float, lon0: float, mode: int,
               flashes_df: pd.DataFrame, events_df: pd.DataFrame | None,
               start_local: datetime, end_local: datetime,
               last_update_local: datetime,
               table: TableRender,
             background: BackgroundImage | None = None,
               alert_rings: set[int] | None = None,
               status_text: str | None = None) -> None:
        self.clear()

        max_r = float(max(self.radii_km))
        self._set_extent(lat0, lon0, max_r)

        if background is not None:
            try:
                self.ax.imshow(
                    background.data,
                    extent=background.extent,
                    origin=background.origin,
                    cmap=_resolve_background_cmap(background.cmap),
                    alpha=float(background.alpha),
                    vmin=background.vmin,
                    vmax=background.vmax,
                    zorder=0,
                    aspect="auto",
                )
            except Exception:
                pass

        self._plot_rings(lat0, lon0, alert_ring_idx=alert_rings)

        # Filter time ranges for plot
        fdf = flashes_df
        if not fdf.empty:
            # Keep only within user range
            fdf = fdf[(fdf["time"].dt.tz_convert(start_local.tzinfo) >= start_local) & (fdf["time"].dt.tz_convert(start_local.tzinfo) <= end_local)]
            if len(fdf) > self.max_points:
                fdf = fdf.sample(self.max_points, random_state=0)

        edf = events_df
        if edf is not None and not edf.empty:
            edf = edf[(edf["time"].dt.tz_convert(start_local.tzinfo) >= start_local) & (edf["time"].dt.tz_convert(start_local.tzinfo) <= end_local)]
            if len(edf) > self.max_points:
                edf = edf.sample(self.max_points, random_state=0)

        # Polygon is always built from events when available (fallback: flashes).
        poly_df: pd.DataFrame | None = None
        if edf is not None and not edf.empty:
            poly_df = edf
        elif not fdf.empty:
            poly_df = fdf
        if poly_df is not None and not poly_df.empty:
            self._draw_polygon(poly_df["lon"].to_numpy(), poly_df["lat"].to_numpy())

        if mode == 1:
            self._plot_scatter_timecolored(fdf, start_local=start_local, end_local=end_local)
        elif mode == 2:
            self._plot_density(fdf)
        elif mode == 3:
            if edf is None:
                edf = pd.DataFrame(columns=["time", "lat", "lon"])
            self.ax.scatter(edf["lon"].to_numpy(), edf["lat"].to_numpy(), s=18, c="#7f7f7f", edgecolors="none")
        elif mode == 4:
            if edf is None:
                edf = pd.DataFrame(columns=["time", "lat", "lon"])
            self._plot_density(edf)

        self.ax.set_title(taker_name, fontsize=14)
        self.ax.set_xlabel("Longitude")
        self.ax.set_ylabel("Latitude")
        self.ax.grid(True, alpha=0.25)
        self.ax.text(
            0.02,
            0.98,
            f"Última atualização: {last_update_local:%H:%M:%S} (local)",
            transform=self.ax.transAxes,
            va="top",
            fontsize=10,
        )
        if status_text:
            self.ax.text(0.02, 0.92, status_text, transform=self.ax.transAxes, va="top", fontsize=10, color="#cc0000")

        self._render_table(table)
        self.fig.tight_layout()
        self.fig.canvas.draw_idle()

        # Keep GUI responsive when interactive; avoid warnings on non-interactive backends.
        try:
            backend = str(matplotlib.get_backend()).lower()
        except Exception:
            backend = ""
        if backend == "agg" or "backend_inline" in backend:
            return
        plt.pause(0.001)
