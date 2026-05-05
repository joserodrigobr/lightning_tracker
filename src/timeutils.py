from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from datetime import timezone


@dataclass(frozen=True)
class TimeRange:
    start_local: datetime
    end_local: datetime


def local_now() -> datetime:
    return datetime.now().astimezone()


def default_timerange() -> TimeRange:
    now = local_now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return TimeRange(start_local=start, end_local=now)


def parse_time_input(user_text: str, *, base_date_local: datetime) -> datetime:
    """Accepts 'HH:MM:SS' (today) or full ISO 'YYYY-MM-DD HH:MM:SS'."""

    text = (user_text or "").strip()
    if not text:
        return base_date_local

    # ISO datetime
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=base_date_local.tzinfo)
        except ValueError:
            pass

    # Time only
    try:
        t = datetime.strptime(text, "%H:%M:%S").time()
        return base_date_local.replace(hour=t.hour, minute=t.minute, second=t.second, microsecond=0)
    except ValueError as e:
        raise ValueError("Formato inválido. Use HH:MM:SS ou YYYY-MM-DD HH:MM:SS") from e


def to_utc(dt_local: datetime) -> datetime:
    return dt_local.astimezone(timezone.utc)


def clamp_history_end(end_local: datetime, history_hours: int) -> tuple[datetime, datetime]:
    end = end_local
    start = end - timedelta(hours=history_hours)
    return start, end
