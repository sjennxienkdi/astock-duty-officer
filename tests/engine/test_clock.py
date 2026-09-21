"""虚拟时钟与节奏表（plan §7 / §3.2）断言。"""

from __future__ import annotations

from datetime import timedelta

import pytest

from conftest import DAY, at
from duty_engine.clock import (
    SCHEDULE,
    SystemClock,
    VirtualClock,
    due_entries,
    ensure_shanghai,
    next_entry,
    shanghai,
)


def test_clock_rejects_naive() -> None:
    with pytest.raises(ValueError):
        ensure_shanghai(at("08:20").replace(tzinfo=None))


def test_clock_virtual_advance_and_set() -> None:
    clock = VirtualClock(at("08:19"))
    clock.advance(timedelta(minutes=1))
    assert clock.now().strftime("%H:%M") == "08:20"
    clock.set(at("15:12"))
    assert clock.now().strftime("%H:%M") == "15:12"


def test_clock_system_is_shanghai() -> None:
    assert ensure_shanghai(SystemClock().now()).utcoffset() == timedelta(hours=8)


def test_clock_schedule_freezes_wall_times() -> None:
    slots = {(e.name, e.at.strftime("%H:%M")) for e in SCHEDULE}
    expected = {
        ("screener_deep_research", "23:30"),
        ("lock_pool", "08:20"),
        ("decision_deadline", "08:44"),
        ("lock_plan", "08:45"),
        ("daily_summary", "15:12"),
        ("backup_and_ingest", "15:30"),
    }
    assert expected <= slots


def test_clock_due_and_next() -> None:
    clock = VirtualClock(shanghai(2026, 9, 16, "08:44:30"))
    due = [e.name for e in due_entries(clock, DAY)]
    assert "lock_pool" in due and "lock_plan" not in due
    following = next_entry(clock, DAY)
    assert following is not None and following.name == "lock_plan"


def test_clock_after_close_nothing_pending() -> None:
    assert next_entry(VirtualClock(at("16:00")), DAY) is None


def test_clock_night_band_belongs_to_previous_day() -> None:
    evening = [e for e in due_entries(VirtualClock(at("16:00")), DAY) if e.day_offset == -1]
    assert {e.name for e in evening} == {"screener_deep_research", "diligence_night"}
    assert evening[0].occurs_on(DAY).strftime("%Y-%m-%d") == "2026-09-15"
