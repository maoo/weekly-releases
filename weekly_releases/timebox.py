from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator


def iso_week_file(base_dir: Path, target: date) -> Path:
    iso = target.isocalendar()
    return base_dir / f"{iso.year}" / f"{iso.week:02d}.md"


def release_iso_week(released_at: datetime) -> tuple[int, int]:
    """UTC calendar ISO week ``(year, week)`` for a release timestamp."""
    iso = released_at.astimezone(timezone.utc).date().isocalendar()
    return iso.year, iso.week


def iso_week_bounds(year: int, week: int) -> tuple[datetime, datetime]:
    """Return ``[Monday 00:00 UTC, next Monday 00:00 UTC)`` for an ISO week."""
    monday = date.fromisocalendar(year, week, 1)
    next_monday = monday + timedelta(days=7)
    start = datetime.combine(monday, datetime.min.time(), tzinfo=timezone.utc)
    end = datetime.combine(next_monday, datetime.min.time(), tzinfo=timezone.utc)
    return start, end


def current_week_bounds(today: date) -> tuple[datetime, datetime]:
    """Bounds for the ISO week containing ``today``, capped at end of ``today``."""
    iso = today.isocalendar()
    start, week_end = iso_week_bounds(iso.year, iso.week)
    today_end = datetime.combine(today, datetime.max.time(), tzinfo=timezone.utc)
    end = min(week_end, today_end)
    return start, end


def iso_weeks_between(start: date, end: date) -> Iterator[tuple[int, int]]:
    """Yield ``(iso_year, iso_week)`` for each ISO week from ``start`` through ``end`` inclusive."""
    if end < start:
        return
    s_iso = start.isocalendar()
    monday = date.fromisocalendar(s_iso.year, s_iso.week, 1)
    while monday <= end:
        iso = monday.isocalendar()
        yield iso.year, iso.week
        monday += timedelta(days=7)
