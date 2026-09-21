"""盘中三判定与调频（plan §5.5）断言。"""

from __future__ import annotations

from datetime import datetime

import pytest

from conftest import AT_PLAN_LOCK
from duty_engine.aggregate import Stance
from duty_engine.freeze import Plan, Sizing, Target
from duty_engine.monitor import (
    Frequency,
    MonitorConfig,
    Snapshot,
    initial_frequency,
    judge,
    step_frequency,
)

CONFIG = MonitorConfig()
VMA5 = {"000001": 10_000, "600519": 20_000}


def plan_of(*targets: Target) -> Plan:
    return Plan(pool_version="2026-09-16-0820", locked_at=AT_PLAN_LOCK, targets=targets)


def target(code: str, line: int) -> Target:
    return Target(
        code=code,
        name=f"样本{code}",
        stance=Stance.HOLD,
        target_bps=500,
        current_bps=500,
        protect_trigger_cents=line,
        conflict=False,
        votes=1,
    )


def snapshot(
    code: str,
    price: int,
    volume: int = 1_000,
    prev_close: int = 1_000,
    at: datetime | None = None,
) -> Snapshot:
    return Snapshot(
        code=code,
        name=f"样本{code}",
        at=at or AT_PLAN_LOCK,
        price_cents=price,
        volume_lots=volume,
        prev_close_cents=prev_close,
    )


def test_monitor_protection_uses_frozen_line() -> None:
    """保护线只读 Plan 里的冻结值，引擎不在盘中重算。"""
    plan = plan_of(target("000001", 1_164), target("600519", 900))
    hit = judge(snapshot("000001", 1_000), plan, VMA5, CONFIG)
    miss = judge(snapshot("600519", 1_000), plan, VMA5, CONFIG)
    assert hit is not None and hit.kind == "protect"
    assert "1164" in hit.detail
    assert miss is None


def test_monitor_protection_ignores_sizing_changes() -> None:
    """改 Sizing 不影响已冻结计划的判定线。"""
    plan = plan_of(target("000001", 1_164))
    recomputed = Sizing(stop_loss_bps=1)
    assert plan.targets[0].protect_trigger_cents == 1_164
    assert recomputed.stop_loss_bps == 1
    assert judge(snapshot("000001", 1_200, prev_close=1_200), plan, VMA5, CONFIG) is None


def test_monitor_move_judgment() -> None:
    verdict = judge(snapshot("000001", 950, prev_close=1_000), plan_of(), VMA5, CONFIG)
    assert verdict is not None and verdict.kind == "move"
    assert judge(snapshot("000001", 980, prev_close=1_000), plan_of(), VMA5, CONFIG) is None


def test_monitor_volume_judgment() -> None:
    verdict = judge(snapshot("000001", 1_000, volume=25_000), plan_of(), VMA5, CONFIG)
    assert verdict is not None and verdict.kind == "volume"
    assert judge(snapshot("000001", 1_000, volume=24_000), plan_of(), VMA5, CONFIG) is None


def test_monitor_verdict_carries_no_attribution() -> None:
    """判定结论只描述现象：不出现因果连接词。"""
    verdict = judge(
        snapshot("000001", 900, volume=30_000), plan_of(target("000001", 1_164)), VMA5, CONFIG
    )
    assert verdict is not None
    for word in ("因为", "由于", "导致", "消息", "原因"):
        assert word not in verdict.detail


def test_monitor_frequency_escalates_and_decays() -> None:
    freq = initial_frequency(CONFIG)
    assert freq.label == "5min"
    fast = step_frequency(freq, triggered=True, config=CONFIG)
    assert fast.interval_seconds == 60 and fast.fast
    back = fast
    for _ in range(CONFIG.fast_release_rounds):
        back = step_frequency(back, triggered=False, config=CONFIG)
    assert back.label == "5min" and back.quiet_rounds == 0


def test_monitor_frequency_stays_fast_on_new_trigger() -> None:
    fast = Frequency(60, fast=True, quiet_rounds=2)
    again = step_frequency(fast, triggered=True, config=CONFIG)
    assert again.quiet_rounds == 0 and again.fast


def test_monitor_rejects_naive_snapshot_time() -> None:
    naive = AT_PLAN_LOCK.replace(tzinfo=None)
    with pytest.raises(ValueError):
        Snapshot("000001", "样本", naive, 1_000, 1_000, 1_000)
