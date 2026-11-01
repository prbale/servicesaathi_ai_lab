"""Time handling.

Rule: the database stores `timestamptz` (an absolute instant, kept in UTC).
Every *display* and every interpretation of words like "tomorrow" uses Asia/Kolkata.
`now()` is the single clock for the whole app, so tests can freeze it.
"""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .config import get_settings

_frozen_now: datetime | None = None


def tz() -> ZoneInfo:
    return ZoneInfo(get_settings().display_timezone)


def now() -> datetime:
    """Current instant (timezone-aware, UTC)."""
    if _frozen_now is not None:
        return _frozen_now
    return datetime.now(timezone.utc)


def freeze(at: datetime | None) -> None:
    """Test helper: freeze the clock (pass None to unfreeze)."""
    global _frozen_now
    _frozen_now = at.astimezone(timezone.utc) if at else None


def today_local() -> date:
    return now().astimezone(tz()).date()


def local_dt(d: date, hour: int, minute: int = 0) -> datetime:
    """A wall-clock time in Kolkata as an aware datetime."""
    return datetime.combine(d, time(hour, minute), tzinfo=tz())


def to_local(dt: datetime) -> datetime:
    return dt.astimezone(tz())


def fmt_local(dt: datetime) -> str:
    """e.g. 'Mon 02 Nov 2026, 10:00 IST'"""
    return to_local(dt).strftime("%a %d %b %Y, %H:%M IST")


def fmt_date(d: date) -> str:
    return d.strftime("%A, %d %B %Y")


# Named time windows (local hours, start inclusive, end exclusive).
TIME_WINDOWS: dict[str, tuple[int, int]] = {
    "morning": (8, 12),
    "afternoon": (12, 16),
    "evening": (16, 20),
    "any": (0, 24),
}


def window_bounds(d: date, window: str) -> tuple[datetime, datetime]:
    """Return [start, end) instants for a named window or an exact hour like 'at:10'."""
    if window.startswith("at:"):
        h = int(window.split(":")[1])
        return local_dt(d, h), local_dt(d, h) + timedelta(hours=1)
    start_h, end_h = TIME_WINDOWS[window]
    start = local_dt(d, start_h)
    end = local_dt(d, 0) + timedelta(hours=end_h)
    return start, end


def describe_window(window: str) -> str:
    if window.startswith("at:"):
        h = int(window.split(":")[1])
        return f"around {h:02d}:00"
    if window == "any":
        return "any time"
    s, e = TIME_WINDOWS[window]
    return f"{window} ({s:02d}:00–{e:02d}:00)"
