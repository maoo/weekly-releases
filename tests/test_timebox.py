from datetime import date, datetime, timezone
from pathlib import Path

from weekly_releases.timebox import (
    current_week_bounds,
    iso_week_bounds,
    iso_week_file,
    iso_weeks_between,
    release_iso_week,
)


def test_iso_week_file():
    path = iso_week_file(Path("releases"), date(2026, 1, 8))
    assert str(path).endswith("2026/02.md")


def test_release_iso_week_matches_utc_isocalendar():
    dt = datetime(2026, 1, 8, 15, 30, tzinfo=timezone.utc)
    assert release_iso_week(dt) == (2026, 2)


def test_iso_week_bounds_returns_monday_to_next_monday_utc():
    start, end = iso_week_bounds(2026, 2)
    assert start.date().isoformat() == "2026-01-05"
    assert end.date().isoformat() == "2026-01-12"
    assert start.tzinfo is not None
    assert end.tzinfo is not None


def test_current_week_bounds_caps_at_today_end_of_day():
    # 2026-01-08 is a Thursday in ISO week 2026-W02 (Mon 2026-01-05).
    start, end = current_week_bounds(date(2026, 1, 8))
    assert start.date().isoformat() == "2026-01-05"
    assert end.date().isoformat() == "2026-01-08"
    # End must be after start, not at midnight.
    assert end > start


def test_current_week_bounds_on_sunday_caps_at_end_of_sunday():
    # 2026-01-11 is the Sunday of ISO week 2026-W02; scan runs through that calendar day (UTC).
    start, end = current_week_bounds(date(2026, 1, 11))
    assert start.date().isoformat() == "2026-01-05"
    assert end.date().isoformat() == "2026-01-11"
    assert end > start


def test_iso_weeks_between_inclusive():
    weeks = list(iso_weeks_between(date(2026, 1, 1), date(2026, 1, 20)))
    assert weeks == [(2026, 1), (2026, 2), (2026, 3), (2026, 4)]


def test_iso_weeks_between_single_week():
    weeks = list(iso_weeks_between(date(2026, 1, 5), date(2026, 1, 11)))
    assert weeks == [(2026, 2)]


def test_iso_weeks_between_end_before_start_is_empty():
    assert list(iso_weeks_between(date(2026, 1, 10), date(2026, 1, 1))) == []
