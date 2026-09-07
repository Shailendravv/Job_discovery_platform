"""Duration parsing for ``jobctl list --since``/``--new`` (milestone 2)."""

from datetime import timedelta

import pytest

from app.ingest.time_util import parse_duration


def test_parses_hours():
    assert parse_duration("24h") == timedelta(hours=24)


def test_parses_days():
    assert parse_duration("7d") == timedelta(days=7)


def test_parses_minutes():
    assert parse_duration("30m") == timedelta(minutes=30)


def test_parses_weeks():
    assert parse_duration("2w") == timedelta(weeks=2)


def test_is_case_insensitive():
    assert parse_duration("24H") == timedelta(hours=24)


def test_allows_surrounding_whitespace():
    assert parse_duration(" 24h ") == timedelta(hours=24)


@pytest.mark.parametrize("bad", ["", "24", "h", "24x", "-1h", "1.5h"])
def test_rejects_invalid_input(bad):
    with pytest.raises(ValueError):
        parse_duration(bad)
