"""Time helpers: UTC storage <-> America/New_York display, plus
CME/NYSE-ish session classification for MES.

MES trades nearly 23h on Globex, but the terminal's session labels follow
the NY equity session the spec describes:
  premarket  04:00-09:30 ET
  rth        09:30-16:00 ET
  after_hours 16:00-20:00 ET
  closed     otherwise (and weekends)
"""
from __future__ import annotations

from datetime import datetime, date, time, timezone
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
UTC = timezone.utc


def utc_now() -> datetime:
    return datetime.now(UTC)


def to_utc(dt: datetime) -> datetime:
    """Normalize any datetime to tz-aware UTC. Naive input is assumed UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def to_utc_naive(dt: datetime) -> datetime:
    """For DB storage: tz-aware -> UTC, then drop tzinfo (portable across
    SQLite/Postgres column types)."""
    return to_utc(dt).replace(tzinfo=None)


def from_db(dt: datetime | None) -> datetime | None:
    """DB naive-UTC -> tz-aware UTC."""
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def to_ny(dt: datetime) -> datetime:
    return to_utc(dt).astimezone(NY)


def ny_now() -> datetime:
    return datetime.now(NY)


def ny_session_date(dt: datetime | None = None) -> date:
    return to_ny(dt or utc_now()).date()


def session_status(dt: datetime | None = None) -> str:
    ny = to_ny(dt or utc_now())
    if ny.weekday() >= 5:  # Sat/Sun
        return "closed"
    t = ny.time()
    if time(4, 0) <= t < time(9, 30):
        return "premarket"
    if time(9, 30) <= t < time(16, 0):
        return "rth"
    if time(16, 0) <= t < time(20, 0):
        return "after_hours"
    return "closed"


def is_market_hours(dt: datetime | None = None) -> bool:
    """Premarket through after-hours on weekdays — the window in which the
    news job and price polling should be active."""
    return session_status(dt) in ("premarket", "rth", "after_hours")


def iso_utc(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return to_utc(dt).isoformat().replace("+00:00", "Z")


def iso_ny(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return to_ny(dt).isoformat()
