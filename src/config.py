from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Settings:
    root_dir: Path
    update_interval_sec: int
    history_hours: int
    initial_load_hours: int
    initial_load_cap_midnight: bool

    raw_dir: Path
    processed_dir: Path
    enable_download: bool

    aws_bucket: str
    aws_product_prefix: str
    aws_interval_seconds: int
    aws_availability_lag_sec: int

    service_takers_csv: Path

    radii_km: list[float]

    plot_max_points: int
    plot_dpi: int
    plot_show_polygon: bool
    plot_polygon_events_window_minutes: int
    plot_backend: str

    background_enabled: bool
    background_alpha: float
    background_cmap: str
    background_vmin_k: float
    background_vmax_k: float
    background_max_dim: int
    background_cache_dir: Path
    background_bucket: str
    background_product_prefix: str
    background_channel: int

    archive_enabled: bool
    archive_save_on_hour_change: bool
    archive_screenshots_dir: Path
    archive_tables_dir: Path

    notifications_enabled: bool
    notifications_beep: bool


def _deep_get(d: dict[str, Any], path: list[str], default: Any) -> Any:
    cur: Any = d
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def load_settings(settings_path: Path) -> Settings:
    settings_path = settings_path.resolve()
    root_dir = settings_path.parent.parent

    raw_cfg: dict[str, Any] = {}
    if settings_path.exists():
        raw_cfg = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}

    update_interval_sec = int(_deep_get(raw_cfg, ["app", "update_interval_sec"], 300))
    history_hours = int(_deep_get(raw_cfg, ["app", "history_hours"], 24))
    initial_load_hours = int(_deep_get(raw_cfg, ["app", "initial_load_hours"], 0))
    initial_load_cap_midnight = bool(_deep_get(raw_cfg, ["app", "initial_load_cap_midnight"], True))

    raw_dir = root_dir / str(_deep_get(raw_cfg, ["data", "raw_dir"], "data/raw/glm_20s_goes"))
    processed_dir = root_dir / str(_deep_get(raw_cfg, ["data", "processed_dir"], "data/processed"))
    enable_download = bool(_deep_get(raw_cfg, ["data", "enable_download"], True))

    aws_bucket = str(_deep_get(raw_cfg, ["aws", "bucket"], "noaa-goes19"))
    aws_product_prefix = str(_deep_get(raw_cfg, ["aws", "product_prefix"], "GLM-L2-LCFA"))
    aws_interval_seconds = int(_deep_get(raw_cfg, ["aws", "interval_seconds"], 20))
    aws_availability_lag_sec = int(_deep_get(raw_cfg, ["aws", "availability_lag_sec"], 180))

    service_takers_csv = root_dir / str(
        _deep_get(raw_cfg, ["service_takers", "csv_path"], "config/service_takers.csv")
    )

    radii_km = list(_deep_get(raw_cfg, ["geo", "radii_km"], [30, 50, 100, 200]))
    radii_km = [float(x) for x in radii_km]

    plot_max_points = int(_deep_get(raw_cfg, ["plot", "max_points"], 30000))
    plot_dpi = int(_deep_get(raw_cfg, ["plot", "dpi"], 120))
    plot_show_polygon = bool(_deep_get(raw_cfg, ["plot", "show_polygon"], True))
    plot_polygon_events_window_minutes = int(_deep_get(raw_cfg, ["plot", "polygon_events_window_minutes"], 15))
    plot_backend = str(_deep_get(raw_cfg, ["plot", "backend"], "auto"))

    background_enabled = bool(_deep_get(raw_cfg, ["background", "enabled"], False))
    background_alpha = float(_deep_get(raw_cfg, ["background", "alpha"], 0.45))
    background_cmap = str(_deep_get(raw_cfg, ["background", "cmap"], "gray_r"))
    background_vmin_k = float(_deep_get(raw_cfg, ["background", "vmin_k"], 190.0))
    background_vmax_k = float(_deep_get(raw_cfg, ["background", "vmax_k"], 310.0))
    background_max_dim = int(_deep_get(raw_cfg, ["background", "max_dim"], 600))
    background_cache_dir = root_dir / str(_deep_get(raw_cfg, ["background", "cache_dir"], "data/raw/abi_ir"))
    background_bucket = str(_deep_get(raw_cfg, ["background", "bucket"], aws_bucket))
    background_product_prefix = str(_deep_get(raw_cfg, ["background", "product_prefix"], "ABI-L2-CMIPF"))
    background_channel = int(_deep_get(raw_cfg, ["background", "channel"], 13))

    archive_enabled = bool(_deep_get(raw_cfg, ["archive", "enabled"], True))
    archive_save_on_hour_change = bool(_deep_get(raw_cfg, ["archive", "save_on_hour_change"], True))
    archive_screenshots_dir = root_dir / str(
        _deep_get(raw_cfg, ["archive", "screenshots_dir"], "output/screenshots")
    )
    archive_tables_dir = root_dir / str(_deep_get(raw_cfg, ["archive", "tables_dir"], "output/tables"))

    notifications_enabled = bool(_deep_get(raw_cfg, ["notifications", "enabled"], True))
    notifications_beep = bool(_deep_get(raw_cfg, ["notifications", "beep"], True))

    return Settings(
        root_dir=root_dir,
        update_interval_sec=update_interval_sec,
        history_hours=history_hours,
        initial_load_hours=initial_load_hours,
        initial_load_cap_midnight=initial_load_cap_midnight,
        raw_dir=raw_dir,
        processed_dir=processed_dir,
        enable_download=enable_download,
        aws_bucket=aws_bucket,
        aws_product_prefix=aws_product_prefix,
        aws_interval_seconds=aws_interval_seconds,
        aws_availability_lag_sec=aws_availability_lag_sec,
        service_takers_csv=service_takers_csv,
        radii_km=radii_km,
        plot_max_points=plot_max_points,
        plot_dpi=plot_dpi,
        plot_show_polygon=plot_show_polygon,
        plot_polygon_events_window_minutes=plot_polygon_events_window_minutes,
        plot_backend=plot_backend,
        background_enabled=background_enabled,
        background_alpha=background_alpha,
        background_cmap=background_cmap,
        background_vmin_k=background_vmin_k,
        background_vmax_k=background_vmax_k,
        background_max_dim=background_max_dim,
        background_cache_dir=background_cache_dir,
        background_bucket=background_bucket,
        background_product_prefix=background_product_prefix,
        background_channel=background_channel,
        archive_enabled=archive_enabled,
        archive_save_on_hour_change=archive_save_on_hour_change,
        archive_screenshots_dir=archive_screenshots_dir,
        archive_tables_dir=archive_tables_dir,
        notifications_enabled=notifications_enabled,
        notifications_beep=notifications_beep,
    )
