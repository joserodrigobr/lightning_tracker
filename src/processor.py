from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path

import numpy as np
import pandas as pd
from netCDF4 import Dataset  # type: ignore


@dataclass(frozen=True)
class Points:
    df: pd.DataFrame  # columns: time (UTC), lat, lon


def _parse_iso_utc(s: str) -> datetime:
    s = (s or "").strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def _get_attr(ds: Dataset, names: list[str]) -> str | None:
    for n in names:
        if hasattr(ds, n):
            v = getattr(ds, n)
            if isinstance(v, bytes):
                v = v.decode("utf-8", errors="ignore")
            return str(v)
    return None


def _read_var(ds: Dataset, candidates: list[str]) -> np.ndarray:
    for name in candidates:
        if name in ds.variables:
            arr = ds.variables[name][:]
            return np.asarray(arr)
    raise KeyError(f"Nenhuma variável encontrada: {candidates}")


def extract_points_from_lcfa(file_path: Path, *, kind: str = "flash") -> Points:
    """Extract points from a GLM-L2-LCFA NetCDF.

    kind: 'flash' or 'event'
    Returns DataFrame with time (timezone-aware UTC), lat, lon.
    """

    kind = kind.lower().strip()
    if kind not in {"flash", "event"}:
        raise ValueError("kind deve ser 'flash' ou 'event'")

    # Windows: netCDF4 may fail to open absolute paths containing non-ASCII characters.
    # If the file lives under the current working directory, prefer a relative ASCII path.
    open_path: str | Path = file_path
    try:
        cwd = Path.cwd().resolve()
        rel = file_path.resolve().relative_to(cwd)
        rel_s = str(rel)
        if rel_s and rel_s.isascii():
            open_path = rel
    except Exception:
        pass

    with Dataset(str(open_path), mode="r") as ds:
        start_attr = _get_attr(ds, ["time_coverage_start", "time_coverage_start_utc", "time_coverage_start_time"]) 
        if not start_attr:
            raise ValueError("Atributo time_coverage_start não encontrado no NetCDF")
        t0 = _parse_iso_utc(start_attr)
        if t0.tzinfo is None:
            t0 = t0.replace(tzinfo=timezone.utc)

        if kind == "flash":
            lat = _read_var(ds, ["flash_lat", "flash_latitude"]).astype(np.float64)
            lon = _read_var(ds, ["flash_lon", "flash_longitude"]).astype(np.float64)
            offsets = _read_var(ds, ["flash_time_offset_of_first_event", "flash_time_offset"]).astype(np.float64)
        else:
            lat = _read_var(ds, ["event_lat", "event_latitude"]).astype(np.float64)
            lon = _read_var(ds, ["event_lon", "event_longitude"]).astype(np.float64)
            offsets = _read_var(ds, ["event_time_offset", "event_time_offset_of_event"]).astype(np.float64)

        # Handle masked values / fill
        mask = np.isfinite(lat) & np.isfinite(lon) & np.isfinite(offsets)
        lat = lat[mask]
        lon = lon[mask]
        offsets = offsets[mask]

        base = pd.Timestamp(t0)
        if base.tz is None:
            base = base.tz_localize("UTC")
        else:
            base = base.tz_convert("UTC")

        times = base + pd.to_timedelta(offsets, unit="s")
        if getattr(times, "tz", None) is None:
            times = times.tz_localize("UTC")
        else:
            times = times.tz_convert("UTC")

        df = pd.DataFrame({"time": times, "lat": lat, "lon": lon})
        return Points(df=df)
