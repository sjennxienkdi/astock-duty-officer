"""测试共用夹具：交易日、两道墙的输入样本、DECISION 构造、告警环境。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

import pytest

from duty_engine.aggregate import Stance
from duty_engine.clock import VirtualClock, shanghai
from duty_engine.freeze import (
    Candidate,
    Confidence,
    DecisionEntry,
    DecisionFile,
    EdgeGate,
    Holding,
    Plan,
    Pool,
    Sizing,
    lock_plan,
    lock_pool,
)
from duty_engine.storage import AlertLog, Archive, Store

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "replay-2026-09-16"

DAY = date(2026, 9, 16)
AT_POOL_LOCK = shanghai(2026, 9, 16, "08:20:00")
AT_PLAN_LOCK = shanghai(2026, 9, 16, "08:45:00")

HELD_CODE = "600519"
FRESH_CODE = "000001"
RED_CODE = "300001"
ST_CODE = "000002"
SMALL_CODE = "688001"
CASH_CENTS = 85_000_000

MakeDecision = Callable[[str, tuple[DecisionEntry, ...], Pool], DecisionFile]
MakeEntry = Callable[[str, str, Stance], DecisionEntry]
MakeCandidate = Callable[..., Candidate]


def at(hh_mm: str) -> datetime:
    """当日上海时区时刻，`HH:MM`。"""
    return shanghai(2026, 9, 16, f"{hh_mm}:00")


def candidate(
    code: str,
    name: str,
    *,
    listed_days: int = 500,
    avg_amount_cents: int = 20_000_000_000,
    is_st: bool = False,
    ref_price_cents: int = 10_00,
    hard_red_flags: frozenset[str] = frozenset(),
) -> Candidate:
    """构造一个默认能过 edge gate 的候选。"""
    return Candidate(
        code=code,
        name=name,
        listed_days=listed_days,
        avg_amount_cents=avg_amount_cents,
        is_st=is_st,
        ref_price_cents=ref_price_cents,
        hard_red_flags=hard_red_flags,
    )


@pytest.fixture
def at_pool_lock() -> datetime:
    return AT_POOL_LOCK


@pytest.fixture
def at_plan_lock() -> datetime:
    return AT_PLAN_LOCK


@pytest.fixture
def alert_env(tmp_path: Path) -> tuple[Store, Archive, AlertLog]:
    store = Store(tmp_path / "duty.sqlite3")
    archive = Archive(tmp_path / "results")
    return store, archive, AlertLog(store, archive)


@pytest.fixture
def candidates() -> list[Candidate]:
    """一只新候选 + 一只硬雷 + 一只 ST + 一只缩量 + 一只已持仓。"""
    return [
        candidate(FRESH_CODE, "平安银行", ref_price_cents=1_200),
        candidate(RED_CODE, "样本造假", hard_red_flags=frozenset({"credit_default"})),
        candidate(ST_CODE, "样本ST", is_st=True),
        candidate(SMALL_CODE, "样本缩量", avg_amount_cents=1_000_000_000),
        candidate(HELD_CODE, "贵州茅台", ref_price_cents=150_000),
    ]


@pytest.fixture
def holdings() -> list[Holding]:
    return [Holding(code=HELD_CODE, name="贵州茅台", qty_lots=1, cost_cents=13_500_000)]


@pytest.fixture
def pool(candidates: list[Candidate], holdings: list[Holding]) -> Pool:
    return lock_pool(candidates, holdings, AT_POOL_LOCK, cash_cents=CASH_CENTS)


@pytest.fixture
def entry() -> MakeEntry:
    def _make(code: str, name: str, stance: Stance) -> DecisionEntry:
        return DecisionEntry(
            code=code,
            name=name,
            stance=stance,
            confidence=Confidence.HIGH,
            dd_ref="无背调",
            evidence=("[ifind_panel@2026-09-16T08:30:00+08:00] 样本证据",),
            reasoning="样本理由。",
        )

    return _make


@pytest.fixture
def make_decision() -> MakeDecision:
    def _make(tag: str, entries: tuple[DecisionEntry, ...], target: Pool) -> DecisionFile:
        return DecisionFile(
            tag=tag, as_of=AT_PLAN_LOCK, pool_version=target.pool_version, entries=entries
        )

    return _make


@pytest.fixture
def plan(pool: Pool, make_decision: MakeDecision, entry: MakeEntry) -> Plan:
    decision = make_decision("gpt", (entry(HELD_CODE, "贵州茅台", Stance.HOLD),), pool)
    return lock_plan([decision], pool, AT_PLAN_LOCK)


@pytest.fixture
def sizing() -> Sizing:
    return Sizing()


@pytest.fixture
def gate() -> EdgeGate:
    return EdgeGate()


@pytest.fixture
def clock() -> VirtualClock:
    return VirtualClock(shanghai(2026, 9, 16, "07:00:00"))
