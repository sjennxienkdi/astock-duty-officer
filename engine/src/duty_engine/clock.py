"""时刻表与虚拟时钟（plan §7 / §3.2）。所有 agent 不挂钟，定时只有这里。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")


class Clock(Protocol):
    """引擎唯一时间源。"""

    def now(self) -> datetime: ...


class SystemClock:
    """真实时钟，锁定 Asia/Shanghai。"""

    def now(self) -> datetime:
        return datetime.now(TZ_SHANGHAI)


class VirtualClock:
    """测试用虚拟时钟，可注入并可步进。"""

    def __init__(self, start: datetime) -> None:
        self._now = ensure_shanghai(start)

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> datetime:
        self._now += delta
        return self._now

    def set(self, moment: datetime) -> datetime:
        self._now = ensure_shanghai(moment)
        return self._now


def ensure_shanghai(moment: datetime) -> datetime:
    """拒绝 naive 时间（plan §14），并归一到上海时区。"""
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError(f"禁止 naive datetime: {moment}")
    return moment.astimezone(TZ_SHANGHAI)


def shanghai(year: int, month: int, day: int, hh_mm_ss: str = "00:00:00") -> datetime:
    """按上海时区构造时刻，供 fixture 与测试使用。"""
    hour, minute, second = (int(part) for part in hh_mm_ss.split(":"))
    return datetime(year, month, day, hour, minute, second, tzinfo=TZ_SHANGHAI)


def is_trading_day(day: date) -> bool:
    """周一至周五为交易日，法定节假日不建模（展示模式）。"""
    return day.weekday() < 5


@dataclass(frozen=True)
class ScheduleEntry:
    """一个定时槽：`day_offset` 相对交易日 T，-1 表示盘后夜档。"""

    name: str
    day_offset: int
    at: time
    actor: str

    def occurs_on(self, day: date) -> datetime:
        target = day + timedelta(days=self.day_offset)
        return datetime.combine(target, self.at, tzinfo=TZ_SHANGHAI)


# plan §3.2 节奏表，时刻与执行者冻结
SCHEDULE: tuple[ScheduleEntry, ...] = (
    ScheduleEntry("screener_deep_research", -1, time(23, 30), "screener"),
    ScheduleEntry("diligence_night", -1, time(23, 40), "diligence"),
    ScheduleEntry("service_start", 0, time(7, 30), "engine"),
    ScheduleEntry("director_kickoff", 0, time(7, 55), "director"),
    ScheduleEntry("pack_collect", 0, time(7, 55), "engine"),
    ScheduleEntry("news_index", 0, time(7, 55), "news"),
    ScheduleEntry("screener_revise", 0, time(7, 55), "screener"),
    ScheduleEntry("diligence_morning", 0, time(8, 0), "diligence"),
    ScheduleEntry("lock_pool", 0, time(8, 20), "engine"),
    ScheduleEntry("decision_window", 0, time(8, 20), "decision"),
    ScheduleEntry("decision_deadline", 0, time(8, 44), "decision"),
    ScheduleEntry("lock_plan", 0, time(8, 45), "engine"),
    ScheduleEntry("review", 0, time(8, 45), "review"),
    ScheduleEntry("plan_doc", 0, time(9, 0), "director"),
    ScheduleEntry("intraday_watch", 0, time(9, 30), "watch"),
    ScheduleEntry("noon_report", 0, time(11, 32), "director"),
    ScheduleEntry("afternoon_watch", 0, time(13, 0), "watch"),
    ScheduleEntry("reconcile", 0, time(15, 10), "engine"),
    ScheduleEntry("daily_summary", 0, time(15, 12), "director"),
    ScheduleEntry("backup_and_ingest", 0, time(15, 30), "engine"),
)


def entries_for_day(day: date) -> list[ScheduleEntry]:
    """当天需要触发的定时槽，按时刻排序。"""
    return sorted(
        (e for e in SCHEDULE if is_trading_day(day + timedelta(days=e.day_offset))),
        key=lambda e: (e.day_offset, e.at),
    )


def next_entry(clock: Clock, day: date) -> ScheduleEntry | None:
    """返回 `day` 内尚未执行的下一个定时槽。"""
    now = ensure_shanghai(clock.now())
    pending = [e for e in entries_for_day(day) if e.occurs_on(day) > now]
    return pending[0] if pending else None


def due_entries(clock: Clock, day: date) -> list[ScheduleEntry]:
    """返回 `day` 内已到点但按声明顺序应已执行的定时槽。"""
    now = ensure_shanghai(clock.now())
    return [e for e in entries_for_day(day) if e.occurs_on(day) <= now]
