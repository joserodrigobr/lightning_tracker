from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
from typing import Literal

import numpy as np

import boto3
from botocore import UNSIGNED
from botocore.client import Config


@dataclass(frozen=True)
class BackgroundImage:
    data: np.ndarray
    extent: tuple[float, float, float, float]  # lon_min, lon_max, lat_min, lat_max
    cmap: str
    alpha: float
    vmin: float | None = None
    vmax: float | None = None
    origin: Literal["upper", "lower"] = "upper"
    label: str | None = None


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _day_of_year(dt_utc: datetime) -> int:
    return int(dt_utc.strftime("%j"))


def _diag_set(
    diag: dict[str, str] | None,
    key: str,
    value: object,
    *,
    overwrite: bool = True,
) -> None:
    if diag is None:
        return
    if not overwrite and key in diag:
        return
    try:
        diag[key] = str(value)
    except Exception:
        diag[key] = repr(value)


class AbiIrBackgroundProvider:
    """GOES-19 ABI IR (CMIPF, typically channel 13) background provider.

    Downloads NetCDF from NOAA public S3 and prepares a small subset image to overlay on lon/lat axes.

    NOTE: Requires `pyproj` when enabled.
    """

    def __init__(
        self,
        *,
        bucket: str,
        product_prefix: str,
        channel: int,
        cache_dir: Path,
        alpha: float = 0.45,
        cmap: str = "gray_r",
        vmin_k: float = 190.0,
        vmax_k: float = 310.0,
        max_dim: int = 600,
    ) -> None:
        self.bucket = bucket
        self.product_prefix = product_prefix
        self.channel = int(channel)
        self.cache_dir = cache_dir

        self.alpha = float(alpha)
        self.cmap = str(cmap)
        self.vmin_k = float(vmin_k)
        self.vmax_k = float(vmax_k)
        self.max_dim = int(max_dim)

        self.s3 = boto3.client(
            "s3",
            config=Config(
                signature_version=UNSIGNED,
                connect_timeout=5,
                read_timeout=10,
                retries={"max_attempts": 2, "mode": "standard"},
            ),
        )

        # Cache per hour prefix -> sorted list of (start_dt_utc, key)
        self._hour_index: dict[str, list[tuple[datetime, str]]] = {}
        self._stamp_re = re.compile(r"_s(\d{14})_")

        self._cache_token: tuple[object, ...] | None = None
        self._cache_image: BackgroundImage | None = None

        self._cleanup_manager: object | None = None

    def _prefix_for_hour(self, dt_utc: datetime) -> str:
        dt_utc = _utc(dt_utc)
        doy = _day_of_year(dt_utc)
        return f"{self.product_prefix}/{dt_utc.year}/{doy:03d}/{dt_utc.hour:02d}/"

    def cleanup_cache(self, older_than_days: int = 3) -> int:
        """Delete .nc files from cache older than N days.

        Returns:
            Number of files deleted
        """
        if self._cleanup_manager is None:
            from .cleanup import FileCleanupManager
            self._cleanup_manager = FileCleanupManager()
        return self._cleanup_manager.cleanup_background_cache(self.cache_dir, older_than_days)

    def _stamp_to_dt(self, stamp14: str) -> datetime:
        # Stamp is: YYYYJJJHHMMSSs (s = tenths)
        year = int(stamp14[0:4])
        doy = int(stamp14[4:7])
        hour = int(stamp14[7:9])
        minute = int(stamp14[9:11])
        second = int(stamp14[11:13])
        return datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(
            days=doy - 1, hours=hour, minutes=minute, seconds=second
        )

    def _ensure_hour_index(self, prefix: str) -> None:
        if prefix in self._hour_index:
            return

        items: list[tuple[datetime, str]] = []
        paginator = self.s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []) or []:
                key = str(obj.get("Key", ""))
                if not key.endswith(".nc"):
                    continue

                # ABI CMIP filenames are channel-specific (e.g. "...M6C13_G19...").
                # Keep only the requested channel to avoid mixing bands.
                chan_token = f"C{self.channel:02d}"
                if chan_token not in key:
                    continue

                m = self._stamp_re.search(key)
                if not m:
                    continue
                try:
                    dt = self._stamp_to_dt(m.group(1))
                except Exception:
                    continue
                items.append((dt, key))

        items.sort(key=lambda t: t[0])
        self._hour_index[prefix] = items

    def _find_best_key(self, dt_utc: datetime) -> tuple[datetime, str] | None:
        dt_utc = _utc(dt_utc)

        # Try current hour then previous hour (handles boundary + publish delay).
        for attempt, candidate_dt in enumerate((dt_utc, dt_utc - timedelta(hours=1))):
            prefix = self._prefix_for_hour(candidate_dt)
            self._ensure_hour_index(prefix)
            items = self._hour_index.get(prefix, [])
            if not items:
                continue

            best: tuple[datetime, str] | None = None
            for t, key in items:
                if t <= dt_utc:
                    best = (t, key)
                else:
                    break
            if best is not None:
                return best

        return None

    def _download_key(self, key: str) -> Path:
        parts = key.split("/")
        # .../<product>/<year>/<doy>/<hour>/<filename>
        if len(parts) >= 5:
            year, doy, hour = parts[-4], parts[-3], parts[-2]
            dest_dir = self.cache_dir / year / doy / hour
        else:
            dest_dir = self.cache_dir
        dest_dir.mkdir(parents=True, exist_ok=True)

        filename = key.split("/")[-1]
        dest_path = dest_dir / filename
        if dest_path.exists() and dest_path.stat().st_size > 0:
            print(f"[BG] Cache hit: {dest_path} ({dest_path.stat().st_size} bytes)", flush=True)
            return dest_path

        print(f"[BG] Downloading S3 key: {key}", flush=True)
        print(f"[BG] Destination: {dest_path}", flush=True)
        self.s3.download_file(self.bucket, key, str(dest_path))
        
        if dest_path.exists():
            size = dest_path.stat().st_size
            print(f"[BG] Download complete: {size} bytes", flush=True)
        else:
            print(f"[BG] ERROR: File not found after download: {dest_path}", flush=True)
        
        return dest_path

    def _subset_cmi(
        self,
        file_path: Path,
        *,
        lon_min: float,
        lon_max: float,
        lat_min: float,
        lat_max: float,
        diag: dict[str, str] | None = None,
    ) -> tuple[np.ndarray, str] | None:
        """Return (cmi_subset, origin) or None on failure."""

        try:
            from pyproj import Proj  # type: ignore
        except Exception as e:
            _diag_set(diag, "reason", "missing_pyproj", overwrite=False)
            _diag_set(diag, "detail", f"{type(e).__name__}: {e}", overwrite=False)
            return None

        try:
            from netCDF4 import Dataset  # type: ignore
        except Exception as e:
            _diag_set(diag, "reason", "missing_netCDF4", overwrite=False)
            _diag_set(diag, "detail", f"{type(e).__name__}: {e}", overwrite=False)
            return None

        try:
            # Windows: netCDF4 may fail to open absolute paths containing non-ASCII characters.
            # If the cache file lives under the current working directory, prefer an ASCII relative path.
            open_path = file_path
            
            print(f"[BG] File exists check: {file_path.exists()}", flush=True)
            if file_path.exists():
                print(f"[BG] File size: {file_path.stat().st_size} bytes", flush=True)
            
            print(f"[BG] file_path is absolute: {file_path.is_absolute()}", flush=True)
            print(f"[BG] file_path raw: {file_path}", flush=True)
            print(f"[BG] file_path resolved: {file_path.resolve()}", flush=True)
            
            try:
                cwd = Path.cwd().resolve()
                print(f"[BG] Attempting relative_to conversion...", flush=True)
                rel = file_path.resolve().relative_to(cwd)
                rel_s = str(rel)
                print(f"[BG] Relative path succeeded: {rel_s}", flush=True)
                print(f"[BG] Is relative ASCII: {rel_s.isascii()}", flush=True)
                if rel_s and rel_s.isascii():
                    open_path = rel
                    _diag_set(diag, "netcdf_open_path_kind", "relative")
                    _diag_set(diag, "netcdf_open_path", rel_s)
                    print(f"[BG] Using relative path for NetCDF: {rel_s}", flush=True)
                else:
                    print(f"[BG] Relative path is not ASCII, using absolute", flush=True)
            except Exception as e:
                print(f"[BG] Could not use relative path: {type(e).__name__}: {e}", flush=True)
                pass
            if open_path is file_path:
                _diag_set(diag, "netcdf_open_path_kind", "absolute")
                print(f"[BG] Using absolute path for NetCDF: {open_path}", flush=True)

            print(f"[BG] Attempting to open NetCDF with: {str(open_path)}", flush=True)
            with Dataset(str(open_path), mode="r") as ds:
                print(f"[BG] NetCDF opened successfully", flush=True)
                missing = [v for v in ("CMI", "x", "y") if v not in ds.variables]
                if missing:
                    _diag_set(diag, "reason", "netcdf_missing_vars", overwrite=False)
                    _diag_set(diag, "detail", f"missing={','.join(missing)}", overwrite=False)
                    return None

                x = np.asarray(ds.variables["x"][:], dtype=np.float64)
                y = np.asarray(ds.variables["y"][:], dtype=np.float64)

                proj_var = ds.variables.get("goes_imager_projection")
                if proj_var is None:
                    _diag_set(diag, "reason", "netcdf_missing_projection", overwrite=False)
                    _diag_set(diag, "detail", "missing=goes_imager_projection", overwrite=False)
                    return None

                h = float(getattr(proj_var, "perspective_point_height"))
                lon0 = float(getattr(proj_var, "longitude_of_projection_origin"))
                a = float(getattr(proj_var, "semi_major_axis"))
                b = float(getattr(proj_var, "semi_minor_axis"))
                sweep = getattr(proj_var, "sweep_angle_axis", "x")

                # pyproj expects projection plane coordinates in meters; GOES x/y are radians.
                p = Proj(proj="geos", h=h, lon_0=lon0, sweep=sweep, a=a, b=b, units="m")

                # Find x/y scan-angle bounds for our lon/lat bbox corners.
                corners_lon = np.array([lon_min, lon_min, lon_max, lon_max], dtype=np.float64)
                corners_lat = np.array([lat_min, lat_max, lat_min, lat_max], dtype=np.float64)
                try:
                    x_m, y_m = p(corners_lon, corners_lat)
                except Exception as e:
                    _diag_set(diag, "reason", "proj_transform_failed", overwrite=False)
                    _diag_set(diag, "detail", f"{type(e).__name__}: {e}", overwrite=False)
                    return None

                x_rad = np.asarray(x_m, dtype=np.float64) / h
                y_rad = np.asarray(y_m, dtype=np.float64) / h

                if not np.isfinite(x_rad).any() or not np.isfinite(y_rad).any():
                    _diag_set(diag, "reason", "proj_transform_non_finite", overwrite=False)
                    _diag_set(diag, "detail", "x/y not finite", overwrite=False)
                    return None

                x_lo, x_hi = float(np.nanmin(x_rad)), float(np.nanmax(x_rad))
                y_lo, y_hi = float(np.nanmin(y_rad)), float(np.nanmax(y_rad))

                # Indices where scan angles fall inside requested bounds.
                x_idx = np.where((x >= min(x_lo, x_hi)) & (x <= max(x_lo, x_hi)))[0]
                y_idx = np.where((y >= min(y_lo, y_hi)) & (y <= max(y_lo, y_hi)))[0]
                if x_idx.size == 0 or y_idx.size == 0:
                    _diag_set(diag, "reason", "subset_out_of_bounds", overwrite=False)
                    _diag_set(diag, "detail", "bbox outside scan grid", overwrite=False)
                    return None

                x0, x1 = int(x_idx.min()), int(x_idx.max()) + 1
                y0, y1 = int(y_idx.min()), int(y_idx.max()) + 1

                nx = max(1, x1 - x0)
                ny = max(1, y1 - y0)
                step = int(max(1, np.ceil(max(nx, ny) / max(1, self.max_dim))))

                cmi_var = ds.variables["CMI"]
                sub = cmi_var[y0:y1:step, x0:x1:step]
                if hasattr(sub, "filled"):
                    sub = sub.filled(np.nan)
                cmi = np.asarray(sub, dtype=np.float32)

                # Mask implausible ranges (keep Kelvin). Some files may contain fill like -1.
                cmi[~np.isfinite(cmi)] = np.nan
                cmi[(cmi < 80.0) | (cmi > 500.0)] = np.nan

                # Determine origin based on y direction in file.
                origin = "upper" if y[y0] > y[min(y1 - 1, len(y) - 1)] else "lower"

                _diag_set(diag, "subset_origin", origin)
                _diag_set(diag, "subset_shape", f"{int(cmi.shape[0])}x{int(cmi.shape[1])}")
                _diag_set(diag, "subset_step", step)
                _diag_set(diag, "subset_finite", int(np.isfinite(cmi).sum()))
                return cmi, origin
        except Exception as e:
            print(f"[BG] NetCDF read error: {type(e).__name__}: {e}", flush=True)
            print(f"[BG] Error trace: {type(e).__module__}.{type(e).__qualname__}", flush=True)
            _diag_set(diag, "reason", "netcdf_read_failed", overwrite=False)
            _diag_set(diag, "detail", f"{type(e).__name__}: {e}", overwrite=False)
            return None

    def get_background(
        self,
        *,
        dt_utc: datetime,
        extent: tuple[float, float, float, float],
        diag: dict[str, str] | None = None,
    ) -> BackgroundImage | None:
        """Return a background image for the given UTC time and lon/lat extent.

        extent: (lon_min, lon_max, lat_min, lat_max)
        """

        print(f"[BG] get_background called, cwd={Path.cwd()}", flush=True)
        print(f"[BG] cache_dir={self.cache_dir}, absolute={self.cache_dir.resolve()}", flush=True)

        lon_min, lon_max, lat_min, lat_max = extent

        dt_utc = _utc(dt_utc)
        _diag_set(diag, "dt_utc", dt_utc.isoformat())
        _diag_set(diag, "extent", f"{lon_min:.3f},{lon_max:.3f},{lat_min:.3f},{lat_max:.3f}")
        _diag_set(diag, "bucket", self.bucket)
        _diag_set(diag, "product_prefix", self.product_prefix)
        _diag_set(diag, "channel", self.channel)
        _diag_set(diag, "prefix0", self._prefix_for_hour(dt_utc))
        _diag_set(diag, "prefix1", self._prefix_for_hour(dt_utc - timedelta(hours=1)))

        try:
            found = self._find_best_key(dt_utc)
        except Exception as e:
            _diag_set(diag, "reason", "s3_list_failed", overwrite=False)
            _diag_set(diag, "detail", f"{type(e).__name__}: {e}", overwrite=False)
            return None
        if found is None:
            _diag_set(diag, "reason", "no_s3_key", overwrite=False)
            return None
        file_time, key = found

        _diag_set(diag, "s3_key", key)
        _diag_set(diag, "file_time_utc", file_time.isoformat())

        token = (
            key,
            round(lon_min, 3),
            round(lon_max, 3),
            round(lat_min, 3),
            round(lat_max, 3),
            int(self.max_dim),
        )
        if token == self._cache_token and self._cache_image is not None:
            _diag_set(diag, "cache", "hit")
            _diag_set(diag, "reason", "ok", overwrite=False)
            return self._cache_image

        _diag_set(diag, "cache", "miss")

        try:
            path = self._download_key(key)
        except Exception as e:
            print(f"[BG] Download failed: {type(e).__name__}: {e}", flush=True)
            _diag_set(diag, "reason", "download_failed", overwrite=False)
            _diag_set(diag, "detail", f"{type(e).__name__}: {e}", overwrite=False)
            return None

        _diag_set(diag, "local_file", path.name)
        print(f"[BG] Starting subset_cmi for: {path}", flush=True)

        subset = self._subset_cmi(
            path,
            lon_min=lon_min,
            lon_max=lon_max,
            lat_min=lat_min,
            lat_max=lat_max,
            diag=diag,
        )
        if subset is None:
            _diag_set(diag, "reason", "subset_failed", overwrite=False)
            return None
        cmi, origin = subset

        finite = int(np.isfinite(cmi).sum())
        _diag_set(diag, "subset_finite", finite, overwrite=False)
        if finite <= 0:
            _diag_set(diag, "warning", "subset_all_nan")

        img = BackgroundImage(
            data=cmi,
            extent=(lon_min, lon_max, lat_min, lat_max),
            cmap=self.cmap,
            alpha=self.alpha,
            vmin=self.vmin_k,
            vmax=self.vmax_k,
            origin=origin,
            label=f"ABI IR C{self.channel:02d} {file_time:%Y-%m-%d %H:%M:%S}Z",
        )

        self._cache_token = token
        self._cache_image = img
        _diag_set(diag, "reason", "ok", overwrite=False)
        return img
