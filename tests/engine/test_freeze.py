"""两道墙（池锁定 / 计划锁定）的引擎断言（plan §13）。"""

from __future__ import annotations

import dataclasses
from datetime import datetime

import pytest

from conftest import (
    AT_PLAN_LOCK,
    CASH_CENTS,
    FRESH_CODE,
    HELD_CODE,
    RED_CODE,
    SMALL_CODE,
    ST_CODE,
    MakeDecision,
    MakeEntry,
    candidate,
)
from duty_engine.aggregate import Stance
from duty_engine.freeze import (
    Candidate,
    DecisionFile,
    EdgeGate,
    Holding,
    Pool,
    Sizing,
    lock_plan,
    lock_pool,
    render_morning,
)
from duty_engine.storage import AlertLog, Archive, Store


def test_lock_pool_hard_red_veto(
    candidates: list[Candidate],
    holdings: list[Holding],
    alert_env: tuple[Store, Archive, AlertLog],
    at_pool_lock: datetime,
) -> None:
    """硬雷只由引擎浅筛否决，并落 ALERT。"""
    store, archive, log = alert_env
    pool = lock_pool(candidates, holdings, at_pool_lock, alert_log=log, cash_cents=CASH_CENTS)
    assert RED_CODE not in pool.codes
    assert any(code == RED_CODE and "硬雷" in reason for code, reason in pool.dropped)
    assert store.alerts("hard_red")
    assert f"kind=hard_red {RED_CODE}" in archive.read(at_pool_lock.date(), "ALERT.md")


def test_lock_pool_holdings_forced_in(holdings: list[Holding], at_pool_lock: datetime) -> None:
    """持仓股即使 ST / 缩量也必须留池——串行漏斗不能悄悄吃掉卖出。"""
    weak = [candidate(HELD_CODE, "贵州茅台", is_st=True, listed_days=10, avg_amount_cents=1)]
    pool = lock_pool(weak, holdings, at_pool_lock, cash_cents=CASH_CENTS)
    assert pool.codes == (HELD_CODE,)
    item = pool.item(HELD_CODE)
    assert item is not None and item.held and item.qty_lots == 1


def test_lock_pool_drops_gate_failures(
    candidates: list[Candidate], holdings: list[Holding], at_pool_lock: datetime
) -> None:
    pool = lock_pool(candidates, holdings, at_pool_lock, cash_cents=CASH_CENTS)
    assert set(pool.codes) == {FRESH_CODE, HELD_CODE}
    assert {code for code, _ in pool.dropped} == {ST_CODE, SMALL_CODE, RED_CODE}


def test_lock_pool_gate_is_configurable(
    candidates: list[Candidate], holdings: list[Holding], at_pool_lock: datetime
) -> None:
    pool = lock_pool(
        candidates,
        holdings,
        at_pool_lock,
        gate=EdgeGate(min_avg_amount_cents=500_000_000),
        cash_cents=CASH_CENTS,
    )
    assert SMALL_CODE in pool.codes


def test_lock_pool_version_and_frozen(
    candidates: list[Candidate], holdings: list[Holding], at_pool_lock: datetime
) -> None:
    pool = lock_pool(candidates, holdings, at_pool_lock, cash_cents=CASH_CENTS)
    assert pool.pool_version == "2026-09-16-0820"
    assert pool.portfolio_cents() == 100_000_000
    with pytest.raises(dataclasses.FrozenInstanceError):
        pool.cash_cents = 1  # type: ignore[misc]


def test_lock_plan_sig001_rejects_whole_file(
    pool: Pool, make_decision: MakeDecision, entry: MakeEntry
) -> None:
    """作废是整份作废：同一份里无辜的那一行也不计票。"""
    clean = make_decision("claude", (entry(FRESH_CODE, "平安银行", Stance.OPEN),), pool)
    dirty = dataclasses.replace(
        make_decision(
            "gpt",
            (
                entry(HELD_CODE, "贵州茅台", Stance.CLEAR),
                entry(FRESH_CODE, "平安银行", Stance.TRIM),
            ),
            pool,
        ),
        voided=True,
        void_reason="命中仓位正则",
    )
    result = lock_plan([clean, dirty], pool, AT_PLAN_LOCK)
    fresh = next(t for t in result.targets if t.code == FRESH_CODE)
    assert (fresh.votes, fresh.stance) == (1, Stance.OPEN)
    held = next(t for t in result.targets if t.code == HELD_CODE)
    assert (held.votes, held.stance) == (0, Stance.HOLD)
    assert result.voided_tags == ("gpt",)


def test_lock_plan_rejects_wrong_pool_version(
    pool: Pool, make_decision: MakeDecision, entry: MakeEntry
) -> None:
    stale = dataclasses.replace(
        make_decision("gpt", (entry(HELD_CODE, "贵州茅台", Stance.HOLD),), pool),
        pool_version="2026-09-15-0820",
    )
    result = lock_plan([stale], pool, AT_PLAN_LOCK)
    assert result.zero_candidate
    assert result.voided_tags == ("gpt",)


def test_lock_plan_all_absent_is_zero_day(pool: Pool) -> None:
    result = lock_plan([], pool, AT_PLAN_LOCK)
    assert result.zero_candidate
    assert result.orders == ()


def test_lock_plan_hold_target_makes_no_order(
    pool: Pool, make_decision: MakeDecision, entry: MakeEntry
) -> None:
    """聚合为持有时按现仓精确持有，非换仓日零订单。"""
    decision = make_decision("gpt", (entry(HELD_CODE, "贵州茅台", Stance.HOLD),), pool)
    result = lock_plan([decision], pool, AT_PLAN_LOCK)
    held = next(t for t in result.targets if t.code == HELD_CODE)
    assert held.target_bps == held.current_bps == 1_500
    assert not held.rebalance
    assert result.orders == ()


def test_lock_plan_open_makes_approved_draft(
    pool: Pool, make_decision: MakeDecision, entry: MakeEntry
) -> None:
    decision = make_decision("gpt", (entry(FRESH_CODE, "平安银行", Stance.OPEN),), pool)
    result = lock_plan([decision], pool, AT_PLAN_LOCK)
    assert len(result.orders) == 1
    order = result.orders[0]
    assert order.side == "buy"
    assert str(order.state) == "approved"
    assert order.amount_cents == 9_960_000


def test_lock_plan_rejects_unaffordable_buy(
    pool: Pool, make_decision: MakeDecision, entry: MakeEntry
) -> None:
    broke = dataclasses.replace(pool, cash_cents=1_000)
    decision = make_decision("gpt", (entry(FRESH_CODE, "平安银行", Stance.OPEN),), broke)
    result = lock_plan([decision], broke, AT_PLAN_LOCK)
    assert str(result.orders[0].state) == "rejected"


def test_lock_plan_trigger_line_is_frozen(
    pool: Pool, make_decision: MakeDecision, entry: MakeEntry
) -> None:
    decision = make_decision("gpt", (entry(HELD_CODE, "贵州茅台", Stance.HOLD),), pool)
    result = lock_plan([decision], pool, AT_PLAN_LOCK, sizing=Sizing(stop_loss_bps=500))
    held = next(t for t in result.targets if t.code == HELD_CODE)
    assert held.protect_trigger_cents == 142_500
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.locked_at = AT_PLAN_LOCK  # type: ignore[misc]


def test_lock_plan_records_absent_tags(
    pool: Pool, make_decision: MakeDecision, entry: MakeEntry
) -> None:
    decision = make_decision("gpt", (entry(HELD_CODE, "贵州茅台", Stance.HOLD),), pool)
    result = lock_plan([decision], pool, AT_PLAN_LOCK, expected_tags=("gpt", "glm"))
    assert result.absent_tags == ("glm",)


def test_lock_plan_ignores_off_pool_code(
    pool: Pool,
    make_decision: MakeDecision,
    entry: MakeEntry,
    alert_env: tuple[Store, Archive, AlertLog],
    at_plan_lock: datetime,
) -> None:
    """计划锁定之后，池外标的进不来。"""
    store, _, log = alert_env
    decision = make_decision("gpt", (entry(RED_CODE, "样本造假", Stance.OPEN),), pool)
    result = lock_plan([decision], pool, at_plan_lock, alert_log=log)
    assert all(t.code != RED_CODE for t in result.targets)
    assert store.alerts("offpool")


def test_render_morning_carries_engine_numbers(
    pool: Pool, make_decision: MakeDecision, entry: MakeEntry
) -> None:
    decision = make_decision("gpt", (entry(FRESH_CODE, "平安银行", Stance.OPEN),), pool)
    result = lock_plan([decision], pool, AT_PLAN_LOCK)
    text = render_morning(result, pool)
    assert "pool_version: 2026-09-16-0820" in text
    assert "portfolio_cents: 100000000" in text
    assert "target_bps: 1000" in text
    assert "protect_trigger_cents: 1164" in text


def test_lock_pool_rejects_unknown_hard_red_flag() -> None:
    with pytest.raises(ValueError):
        candidate("000001", "平安银行", hard_red_flags=frozenset({"随便写的"}))


def test_parse_decision_roundtrip(pool: Pool) -> None:
    from duty_engine.freeze import parse_decision

    text = "\n".join(
        [
            "# DECISION · 2026-09-16 · gpt",
            "as_of: 2026-09-16T08:40:00+08:00",
            f"pool_version: {pool.pool_version}",
            "",
            "## 000001 平安银行",
            "stance: 建仓",
            "confidence: medium",
            "dd_ref: DD/000001/2026-09-15.md",
            "evidence:",
            '  - "[ifind_panel@2026-09-16T08:31:00+08:00] 成交额放量"',
            "reasoning: 样本理由。",
        ]
    )
    parsed = parse_decision(text)
    assert parsed.tag == "gpt"
    assert parsed.entries[0].stance is Stance.OPEN
    assert parsed.entries[0].evidence == ("[ifind_panel@2026-09-16T08:31:00+08:00] 成交额放量",)


@pytest.mark.parametrize(
    "drop", ["as_of", "pool_version", "stance", "confidence", "dd_ref", "reasoning"]
)
def test_parse_decision_missing_field_raises(
    pool: Pool, drop: str, make_decision: MakeDecision
) -> None:
    from duty_engine.freeze import DecisionFormatError, parse_decision

    text = "\n".join(
        [
            "# DECISION · 2026-09-16 · gpt",
            "as_of: 2026-09-16T08:40:00+08:00",
            f"pool_version: {pool.pool_version}",
            "",
            "## 000001 平安银行",
            "stance: 建仓",
            "confidence: medium",
            "dd_ref: 无背调",
            "reasoning: 样本理由。",
        ]
    )
    line = {"as_of": "as_of:", "pool_version": "pool_version:"}.get(drop, f"{drop}:")
    stripped = "\n".join(ln for ln in text.splitlines() if not ln.startswith(line))
    with pytest.raises(DecisionFormatError):
        parse_decision(stripped)


def test_parse_decision_rejects_naive_as_of(pool: Pool) -> None:
    from duty_engine.freeze import parse_decision

    text = (
        "# DECISION · 2026-09-16 · gpt\nas_of: 2026-09-16T08:40:00\n"
        f"pool_version: {pool.pool_version}\n\n## 000001 平安银行\nstance: 建仓\n"
        "confidence: medium\ndd_ref: 无背调\nreasoning: x\n"
    )
    with pytest.raises(ValueError):
        parse_decision(text)


def test_decision_file_is_frozen(pool: Pool, make_decision: MakeDecision, entry: MakeEntry) -> None:
    decision: DecisionFile = make_decision(
        "gpt", (entry(HELD_CODE, "贵州茅台", Stance.HOLD),), pool
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        decision.tag = "y"  # type: ignore[misc]
