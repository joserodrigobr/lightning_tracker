from __future__ import annotations

from pathlib import Path

from src.config import load_settings
from src.mpl_setup import configure_matplotlib_backend


def main() -> None:
    settings = load_settings(Path("config/settings.yaml"))

    # Must happen before importing pyplot (pulled in by src.core/src.visualizer).
    backend = configure_matplotlib_backend(settings.plot_backend)
    print(f"Matplotlib backend: {backend}")

    from src.core import run
    from src.service_takers import load_service_takers
    from src.ui import ask_selection

    takers = load_service_takers(settings.service_takers_csv)
    sel = ask_selection(takers, default_initial_load_hours=settings.initial_load_hours)
    run(
        settings,
        selection_taker_number=sel.taker_number,
        mode=sel.mode,
        time_range=sel.time_range,
        dynamic_start=sel.dynamic_start,
        dynamic_end=sel.dynamic_end,
        initial_load_hours=sel.initial_load_hours,
    )


if __name__ == "__main__":
    main()
