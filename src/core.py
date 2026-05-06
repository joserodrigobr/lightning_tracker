from __future__ import annotations

import logging
import re
import time
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .archiver import HourlyArchiver
from .config import Settings
from .downloader import GLMDownloader
from .geo import haversine_km, ring_index
from .notifier import beep
from .processor import extract_points_from_lcfa
from .service_takers import ServiceTaker, get_taker_by_number, load_service_takers
from .timeutils import TimeRange, local_now
from .visualizer import TableRender, Visualizer


def _slug(text: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", text.strip())
    return s.strip("_")[:64] or "taker"


_GLM_STAMP_RE = re.compile(r"_s(\d{14})_")


def _glm_start_time_from_name(filename: str) -> datetime | None:
    """Parse GOES stamp _sYYYYJJJHHMMSSs_ into a UTC datetime (seconds precision)."""

    m = _GLM_STAMP_RE.search(filename)
    if not m:
        return None
    stamp = m.group(1)
    try:
        year = int(stamp[0:4])
        doy = int(stamp[4:7])
        hour = int(stamp[7:9])
        minute = int(stamp[9:11])
        second = int(stamp[11:13])
        return datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(
            days=doy - 1, hours=hour, minutes=minute, seconds=second
        )
    except Exception:
        return None


def _setup_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "app.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler()],
    )


def _hour_labels(end_local: datetime) -> list[str]:
    end_hour = end_local.replace(minute=0, second=0, microsecond=0)
    start_hour = end_hour - timedelta(hours=23)
    return [(start_hour + timedelta(hours=i)).strftime("%H") for i in range(24)]


def _5min_time_labels_for_date(date_local: datetime) -> list[str]:
    # Returns 288 labels from 00:00 to 23:55 in HH:MM format for the given local date
    base = date_local.replace(hour=0, minute=0, second=0, microsecond=0)
    return [(base + timedelta(minutes=5 * i)).strftime("%H:%M") for i in range(288)]


def _radii_labels(radii_km: list[float]) -> list[str]:
    rs = radii_km
    return [
        f"0-{int(rs[0])}",
        f"{int(rs[0])}-{int(rs[1])}",
        f"{int(rs[1])}-{int(rs[2])}",
        f"{int(rs[2])}-{int(rs[3])}",
    ]


def compute_table_4x24(flashes_df: pd.DataFrame, *, lat0: float, lon0: float, radii_km: list[float], end_local: datetime) -> np.ndarray:
    if flashes_df.empty:
        return np.zeros((4, 24), dtype=np.int64)

    end_hour_local = end_local.replace(minute=0, second=0, microsecond=0)
    start_hour_local = end_hour_local - timedelta(hours=23)
    start_local = start_hour_local
    end_local_inclusive = end_hour_local + timedelta(hours=1)

    df = flashes_df.copy()
    tloc = df["time"].dt.tz_convert(end_local.tzinfo)
    df = df[(tloc >= start_local) & (tloc < end_local_inclusive)]
    if df.empty:
        return np.zeros((4, 24), dtype=np.int64)

    dist = haversine_km(lat0, lon0, df["lat"].to_numpy(), df["lon"].to_numpy())
    r_idx = ring_index(dist, radii_km)
    within = r_idx < len(radii_km)
    df = df[within].copy()
    if df.empty:
        return np.zeros((4, 24), dtype=np.int64)
    df["ring"] = r_idx[within]

    hour = df["time"].dt.tz_convert(end_local.tzinfo).dt.floor("h")
    df["hour"] = hour

    hours = [start_hour_local + timedelta(hours=i) for i in range(24)]
    table = np.zeros((4, 24), dtype=np.int64)
    for ring in range(4):
        sub = df[df["ring"] == ring]
        if sub.empty:
            continue
        counts = sub.groupby("hour").size()
        for j, h in enumerate(hours):
            table[ring, j] = int(counts.get(h, 0))
    return table


def compute_table_4x5min(flashes_df: pd.DataFrame, *, lat0: float, lon0: float, radii_km: list[float], date_local: datetime) -> np.ndarray:
    """Compute a 4 x 288 table of flash counts using 5-minute bins anchored to local date midnight.

    - `date_local` is any datetime with the desired local date and tzinfo; the function will use
      that date's 00:00..23:55 local time range.
    - Future bins (>= now_local if date_local is today) will remain zero.
    """
    # Prepare empty result
    table = np.zeros((4, 288), dtype=np.int64)
    if flashes_df.empty:
        return table

    # Determine local midnight and day end
    local_midnight = date_local.replace(hour=0, minute=0, second=0, microsecond=0)
    local_day_end = local_midnight + timedelta(days=1)

    # Convert flash times to the local tz of date_local
    tz = date_local.tzinfo
    tloc = flashes_df["time"].dt.tz_convert(tz)
    # Keep only those within the day [midnight, day_end)
    mask = (tloc >= local_midnight) & (tloc < local_day_end)
    df = flashes_df[mask].copy()
    if df.empty:
        return table

    # Compute distances and ring indices
    dist = haversine_km(lat0, lon0, df["lat"].to_numpy(), df["lon"].to_numpy())
    r_idx = ring_index(dist, radii_km)
    within = r_idx < len(radii_km)
    df = df[within].copy()
    if df.empty:
        return table
    df["ring"] = r_idx[within]

    # Compute 5-minute bin index: minutes since midnight // 5 -> 0..287
    minutes = (df["time"].dt.tz_convert(tz).dt.hour * 60) + df["time"].dt.tz_convert(tz).dt.minute
    bin_idx = (minutes // 5).astype(int)
    df["bin"] = bin_idx

    # Filter valid bins 0..287
    df = df[(df["bin"] >= 0) & (df["bin"] < 288)]
    if df.empty:
        return table

    # Group by ring and bin and count
    grp = df.groupby(["ring", "bin"]).size()
    for (ring, b), cnt in grp.items():
        if 0 <= ring < 4 and 0 <= b < 288:
            table[int(ring), int(b)] = int(cnt)

    return table


@dataclass
class RuntimeState:
    flashes: pd.DataFrame
    events: pd.DataFrame
    last_fetch_utc: datetime


def _empty_points_df() -> pd.DataFrame:
    return pd.DataFrame({"time": pd.Series(dtype="datetime64[ns, UTC]"), "lat": [], "lon": []})


def _to_utc(dt_local: datetime) -> datetime:
    if dt_local.tzinfo is None:
        return dt_local.replace(tzinfo=timezone.utc)
    return dt_local.astimezone(timezone.utc)


def run(
    settings: Settings,
    *,
    selection_taker_number: int,
    mode: int,
    time_range: TimeRange,
    dynamic_start: bool,
    dynamic_end: bool,
    initial_load_hours: int,
) -> None:
    _setup_logging(settings.root_dir / "logs")
    logging.info("Inicializando visualizador")

    takers = load_service_takers(settings.service_takers_csv)
    taker = get_taker_by_number(takers, selection_taker_number)
    taker_slug = _slug(taker.unidade)

    viz = Visualizer(
        radii_km=settings.radii_km,
        max_points=settings.plot_max_points,
        dpi=settings.plot_dpi,
        show_polygon=settings.plot_show_polygon,
    )

    should_stop = False
    manual_save = False

    def _on_key(event) -> None:
        nonlocal should_stop, manual_save
        key = (getattr(event, "key", "") or "").lower()
        if key == "q":
            should_stop = True
        elif key == "s":
            manual_save = True

    try:
        viz.fig.canvas.mpl_connect("key_press_event", _on_key)
    except Exception:
        pass

    archiver = HourlyArchiver(
        enabled=settings.archive_enabled,
        screenshots_root=settings.archive_screenshots_dir,
        tables_root=settings.archive_tables_dir,
        save_on_hour_change=settings.archive_save_on_hour_change,
    )

    downloader = GLMDownloader(bucket=settings.aws_bucket, product_prefix=settings.aws_product_prefix, goes_number=19)

    # We always need flashes; events are required for modes 3/4 and for the polygon-by-events overlay.
    need_events = (mode in (3, 4)) or bool(settings.plot_show_polygon)
    events_full_history = (mode in (3, 4))

    now_local = local_now()
    now_utc = now_local.astimezone(timezone.utc)
    lag = timedelta(seconds=int(settings.aws_availability_lag_sec))
    effective_now_utc = now_utc - lag

    # Initial backfill window.
    init_hours = max(0, int(initial_load_hours))
    init_hours = min(init_hours, int(settings.history_hours))
    if init_hours > 0:
        init_start_utc = effective_now_utc - timedelta(hours=init_hours)
        if settings.initial_load_cap_midnight:
            midnight_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
            midnight_utc = midnight_local.astimezone(timezone.utc)
            if init_start_utc < midnight_utc:
                init_start_utc = midnight_utc

        expected = int(max(0.0, (effective_now_utc - init_start_utc).total_seconds()) // int(settings.aws_interval_seconds)) + 1
        logging.info(
            "Carga inicial: %sh (cap_00h=%s) | Janela: %s -> %s UTC | ~%s arquivos",
            init_hours,
            settings.initial_load_cap_midnight,
            init_start_utc.strftime("%Y-%m-%d %H:%M:%S"),
            effective_now_utc.strftime("%Y-%m-%d %H:%M:%S"),
            expected,
        )
        initial_last_fetch_utc = init_start_utc
    else:
        initial_last_fetch_utc = effective_now_utc - timedelta(minutes=5)

    state = RuntimeState(
        flashes=_empty_points_df(),
        events=_empty_points_df(),
        last_fetch_utc=initial_last_fetch_utc,
    )

    fetch_worker_lock = threading.Lock()
    fetch_worker_thread: threading.Thread | None = None
    fetch_worker_result: dict[str, object] | None = None

    def _start_fetch_worker(fetch_start: datetime, fetch_end: datetime) -> None:
        nonlocal fetch_worker_thread, fetch_worker_result
        if fetch_worker_thread is not None and fetch_worker_thread.is_alive():
            return

        fetch_worker_result = None

        def _worker() -> None:
            nonlocal fetch_worker_result
            worker_result: dict[str, object] = {
                "fetch_start": fetch_start,
                "fetch_end": fetch_end,
                "downloaded": 0,
                "not_found": 0,
                "status": "",
                "flashes": _empty_points_df(),
                "events": _empty_points_df(),
            }
            try:
                worker_downloader = GLMDownloader(
                    bucket=settings.aws_bucket,
                    product_prefix=settings.aws_product_prefix,
                    goes_number=19,
                )
                dl = worker_downloader.download_range(
                    fetch_start,
                    fetch_end,
                    interval_seconds=settings.aws_interval_seconds,
                    dest_root=settings.raw_dir,
                )
                worker_result["downloaded"] = len(dl.downloaded)
                worker_result["not_found"] = len(dl.not_found)
                worker_result["status"] = f"Baixados: {len(dl.downloaded)} | Não encontrados: {len(dl.not_found)}"

                events_extract_start_utc = fetch_start
                if need_events and not events_full_history:
                    events_extract_start_utc = max(
                        fetch_start,
                        fetch_end - timedelta(minutes=int(settings.plot_polygon_events_window_minutes)),
                    )

                flashes_frames: list[pd.DataFrame] = []
                events_frames: list[pd.DataFrame] = []
                for p in dl.downloaded:
                    try:
                        pts = extract_points_from_lcfa(p, kind="flash").df
                        flashes_frames.append(pts)

                        if need_events:
                            if events_full_history:
                                do_events = True
                            else:
                                file_dt = _glm_start_time_from_name(p.name)
                                do_events = (file_dt is None) or (file_dt >= events_extract_start_utc)

                            if do_events:
                                epts = extract_points_from_lcfa(p, kind="event").df
                                events_frames.append(epts)
                    except Exception:
                        continue

                if flashes_frames:
                    worker_result["flashes"] = pd.concat(flashes_frames, ignore_index=True)
                if events_frames:
                    worker_result["events"] = pd.concat(events_frames, ignore_index=True)
            except Exception as exc:
                worker_result["status"] = f"Falha no download/processamento: {exc}"
                logging.exception("Falha no download/processamento: %s", exc)

            with fetch_worker_lock:
                fetch_worker_result = worker_result

        fetch_worker_thread = threading.Thread(target=_worker, daemon=True)
        fetch_worker_thread.start()

    def _merge_fetch_worker_result() -> None:
        nonlocal fetch_worker_thread, fetch_worker_result
        if fetch_worker_thread is None or fetch_worker_thread.is_alive():
            return
        if not fetch_worker_result:
            fetch_worker_thread = None
            return

        flashes_df_new = cast(pd.DataFrame, fetch_worker_result.get("flashes", _empty_points_df()))
        events_df_new = cast(pd.DataFrame, fetch_worker_result.get("events", _empty_points_df()))
        if not flashes_df_new.empty:
            state.flashes = pd.concat([state.flashes, flashes_df_new], ignore_index=True)
        if not events_df_new.empty:
            state.events = pd.concat([state.events, events_df_new], ignore_index=True)

        state.last_fetch_utc = cast(datetime, fetch_worker_result.get("fetch_end", state.last_fetch_utc))
        logging.info(str(fetch_worker_result.get("status") or "Fetch worker concluído"))
        fetch_worker_thread = None
        fetch_worker_result = None

    history_delta = timedelta(hours=settings.history_hours)

    # Optional satellite background (ABI IR).
    bg_provider = None
    plot_extent_lonlat = None
    if settings.background_enabled:
        try:
            from .background import AbiIrBackgroundProvider

            bg_provider = AbiIrBackgroundProvider(
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

            # Match Visualizer._set_extent()
            max_r = float(max(settings.radii_km))
            dlat = max_r / 111.0
            dlon = max_r / (111.0 * max(0.2, np.cos(np.radians(taker.latitude))))
            pad = 0.15
            plot_extent_lonlat = (
                taker.longitude - dlon * (1 + pad),
                taker.longitude + dlon * (1 + pad),
                taker.latitude - dlat * (1 + pad),
                taker.latitude + dlat * (1 + pad),
            )
        except Exception:
            logging.exception("Falha ao inicializar background IR; continuando sem overlay")
            bg_provider = None

    logging.info("Rodando loop operacional (%ss)", settings.update_interval_sec)
    while True:
        cycle_start = time.monotonic()
        now_local = local_now()
        now_utc = now_local.astimezone(timezone.utc)

        effective_now_utc = now_utc - lag

        # Fetch & process new data
        fetch_start = state.last_fetch_utc
        fetch_end = effective_now_utc
        if fetch_end <= fetch_start:
            # Nothing new expected yet (publishing lag)
            fetch_end = fetch_start
        new_flash_df = _empty_points_df()
        new_event_df = _empty_points_df()

        status = ""
        if settings.enable_download:
            _merge_fetch_worker_result()
            with fetch_worker_lock:
                worker_busy = fetch_worker_thread is not None and fetch_worker_thread.is_alive()
            if not worker_busy:
                fetch_start = state.last_fetch_utc
                _start_fetch_worker(fetch_start, fetch_end)
                status = "Fetch iniciado em background"
            else:
                status = "Fetch em background"

        # Keep only within max radius for memory/perf
        max_r = float(max(settings.radii_km))
        if not new_flash_df.empty:
            dist = haversine_km(taker.latitude, taker.longitude, new_flash_df["lat"].to_numpy(), new_flash_df["lon"].to_numpy())
            new_flash_df = new_flash_df[dist <= max_r].copy()

        if not new_event_df.empty:
            dist = haversine_km(taker.latitude, taker.longitude, new_event_df["lat"].to_numpy(), new_event_df["lon"].to_numpy())
            new_event_df = new_event_df[dist <= max_r].copy()

        if not new_flash_df.empty:
            state.flashes = pd.concat([state.flashes, new_flash_df], ignore_index=True)
        if not new_event_df.empty:
            state.events = pd.concat([state.events, new_event_df], ignore_index=True)

        # Drop older than history
        cutoff = now_utc - history_delta
        if not state.flashes.empty:
            state.flashes = state.flashes[state.flashes["time"] >= cutoff]

        if not state.events.empty:
            if events_full_history:
                events_cutoff = cutoff
            else:
                events_cutoff = now_utc - timedelta(minutes=int(settings.plot_polygon_events_window_minutes))
            state.events = state.events[state.events["time"] >= events_cutoff]

        # Alerts based on new flashes
        alert_rings: set[int] = set()
        if settings.notifications_enabled and not new_flash_df.empty:
            dist = haversine_km(taker.latitude, taker.longitude, new_flash_df["lat"].to_numpy(), new_flash_df["lon"].to_numpy())
            r_idx = ring_index(dist, settings.radii_km)
            for rid in set(r_idx.tolist()):
                if rid < 4:
                    alert_rings.add(int(rid))
            if alert_rings:
                beep(count=min(3, len(alert_rings)), enabled=settings.notifications_beep)

        # Table always uses flashes
        table_4x24 = compute_table_4x24(state.flashes, lat0=taker.latitude, lon0=taker.longitude, radii_km=settings.radii_km, end_local=now_local)
        table = TableRender(values_4x24=table_4x24, hour_labels=_hour_labels(now_local), radii_labels=_radii_labels(settings.radii_km))

        status_text = None
        if alert_rings:
            labels = table.radii_labels
            status_text = "ALERTA: flashes em " + ", ".join(labels[i] for i in sorted(alert_rings))

        plot_start = time_range.start_local
        plot_end = time_range.end_local
        if dynamic_start:
            plot_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        if dynamic_end:
            plot_end = now_local
        if plot_end < plot_start:
            plot_end = plot_start

        bg = None
        if bg_provider is not None and plot_extent_lonlat is not None:
            try:
                bg = bg_provider.get_background(dt_utc=effective_now_utc, extent=plot_extent_lonlat)
            except Exception:
                bg = None

        viz.update(
            taker_name=f"{taker.unidade}",
            lat0=taker.latitude,
            lon0=taker.longitude,
            mode=mode,
            flashes_df=state.flashes,
            events_df=state.events if need_events else None,
            start_local=plot_start,
            end_local=plot_end,
            last_update_local=now_local,
            table=table,
            background=bg,
            alert_rings=alert_rings,
            status_text=status_text,
        )

        # Manual save (keyboard: 's')
        if manual_save:
            manual_save = False
            png_path, csv_path = archiver.save_snapshot(
                viz.fig,
                table_4x24,
                dt_local=now_local,
                taker_slug=taker_slug,
                mode=mode,
                hours_labels=table.hour_labels,
                radii_labels=table.radii_labels,
                dpi=settings.plot_dpi,
            )
            logging.info("Snapshot manual salvo: %s | %s", png_path, csv_path)

        # Hourly archive
        saved = archiver.maybe_save_hourly(
            viz.fig,
            table_4x24,
            dt_local=now_local,
            taker_slug=taker_slug,
            mode=mode,
            hours_labels=table.hour_labels,
            radii_labels=table.radii_labels,
            dpi=settings.plot_dpi,
        )
        if saved is not None:
            png_path, csv_path = saved
            logging.info("Arquivos salvos: %s | %s", png_path, csv_path)

        if status:
            logging.info(status)

        if should_stop:
            logging.info("Encerrando por comando do usuário (q)")
            break

        elapsed = time.monotonic() - cycle_start
        sleep_for = max(0.0, float(settings.update_interval_sec) - elapsed)

        # Keep the Matplotlib window responsive between cycles.
        try:
            import matplotlib

            backend = str(matplotlib.get_backend()).lower()
            is_interactive = not (backend == "agg" or "backend_inline" in backend)
        except Exception:
            is_interactive = False

        if not is_interactive:
            time.sleep(sleep_for)
        else:
            import matplotlib.pyplot as plt

            deadline = time.monotonic() + sleep_for
            while time.monotonic() < deadline:
                if should_stop or manual_save:
                    break
                remaining = deadline - time.monotonic()
                plt.pause(min(0.25, max(0.0, remaining)))

    try:
        import matplotlib.pyplot as plt

        plt.close(viz.fig)
    except Exception:
        pass
