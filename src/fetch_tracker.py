from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .db import get_conn


class FetchTracker:
    """Simple fetch tracker that persists last-fetched timestamps per product_prefix.

    It prefers DB-derived last_fetched when a Postgres DSN is provided and falls back
    to a JSON state file for standalone deployments.
    """

    def __init__(self, state_path: Path | str = "data/.fetch_state.json"):
        self.state_path = Path(state_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self.state_path.with_suffix(".lock")

    def _read_state(self) -> dict[str, str]:
        if not self.state_path.exists():
            return {}
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _write_state(self, data: dict[str, str]) -> None:
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.state_path)

    def acquire_lock(self) -> bool:
        try:
            # Simple lock: create lock file atomically
            fd = os.open(str(self._lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w") as f:
                f.write(str(os.getpid()))
            return True
        except FileExistsError:
            return False
        except Exception:
            return False

    def release_lock(self) -> None:
        try:
            if self._lock_path.exists():
                self._lock_path.unlink()
        except Exception:
            pass

    def get_last_fetched_from_db(self, dsn: str, product_prefix: str, max_stale_hours: float = 1.0) -> Optional[datetime]:
        try:
            with get_conn(dsn) as conn:
                cur = conn.cursor()
                try:
                    # source_url contains the product prefix; use it to filter
                    cur.execute(
                        "select max(source_time) from raw_files where source_url is not null and source_url like %s",
                        ("%" + product_prefix + "%",),
                    )
                    row = cur.fetchone()
                finally:
                    cur.close()
            if row and row[0] is not None:
                # pg8000 returns datetime objects in UTC
                dt = row[0].replace(tzinfo=timezone.utc) if getattr(row[0], "tzinfo", None) is None else row[0]
                # Staleness guard: if the DB value is too old, treat as None so the
                # caller falls back to the initial-window fetch instead of getting
                # stuck in incremental mode re-downloading already-ingested files.
                age_hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
                if age_hours > max_stale_hours:
                    return None
                return dt
        except Exception:
            return None
        return None

    def get_last_fetched(self, product_prefix: str, dsn: str | None = None) -> Optional[datetime]:
        # Prefer DB when available
        if dsn:
            try:
                db_val = self.get_last_fetched_from_db(dsn, product_prefix)
                if db_val:
                    return db_val
            except Exception:
                pass

        data = self._read_state()
        v = data.get(product_prefix)
        if not v:
            return None
        try:
            return datetime.fromisoformat(v).astimezone(timezone.utc)
        except Exception:
            return None

    def update_last_fetched(self, product_prefix: str, dt: datetime) -> None:
        data = self._read_state()
        # store in ISO-8601 UTC
        data[product_prefix] = dt.astimezone(timezone.utc).isoformat()
        try:
            self._write_state(data)
        except Exception:
            pass
