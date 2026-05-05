from __future__ import annotations

import sys


def beep(count: int = 1, *, enabled: bool = True) -> None:
    if not enabled:
        return
    try:
        import winsound  # type: ignore

        for _ in range(max(1, count)):
            winsound.Beep(1200, 160)
    except Exception:
        # Fallback: terminal bell
        sys.stdout.write("\a")
        sys.stdout.flush()
