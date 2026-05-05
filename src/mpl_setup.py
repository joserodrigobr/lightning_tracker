from __future__ import annotations

import os


def configure_matplotlib_backend(backend: str | None = None) -> str:
    """Configure a GUI backend when running interactively.

    Must be called before importing `matplotlib.pyplot`.

    Rules:
    - If MPLBACKEND is set, respect it.
    - If backend is explicitly provided (not 'auto'), try to force it.
    - If backend='auto' and Matplotlib defaulted to Agg, try a GUI backend.
    """

    # Import here so callers can run this before pyplot is imported.
    import matplotlib

    env_backend = (os.environ.get("MPLBACKEND") or "").strip()

    desired = (backend or "auto").strip()
    if desired and desired.lower() not in {"auto"}:
        # Explicit config wins over environment.
        try:
            matplotlib.use(desired, force=True)
        except Exception:
            # Keep whatever Matplotlib selected.
            pass
        return str(matplotlib.get_backend())

    # Auto mode: if Matplotlib chose a non-interactive backend, try GUI options.
    try:
        current = str(matplotlib.get_backend())
    except Exception:
        current = ""

    # In auto mode, if environment forced Agg (common in some shells/IDEs), try to switch to a GUI backend.
    # If the environment forced a *non-Agg* backend, keep it.
    if env_backend and env_backend.lower() != "agg":
        return str(matplotlib.get_backend())

    if current.lower() == "agg" or "backend_inline" in current.lower():
        for candidate in ("TkAgg", "QtAgg", "Qt5Agg", "WXAgg"):
            try:
                matplotlib.use(candidate, force=True)
                break
            except Exception:
                continue

    return str(matplotlib.get_backend())
