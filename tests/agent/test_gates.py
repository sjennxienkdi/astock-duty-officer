"""角色门禁（plan §13 agent 条目）：禁互读、迟交、盘中护栏、放行链。"""

from __future__ import annotations

from datetime import date

import pytest

from conftest import DAY, GOLDEN_CODES, HELD_CODE, GoldenDay
from duty_agent.agents import decision, review, screener
from duty_agent.graph import permissions_for
from duty_agent.guardrails.intent_guard import TurnLedger, UnverifiedIntent
from duty_agent.planner import IntradayBudget, Planner
from duty_engine.freeze import lock_plan as engine_lock_plan
from duty_engine.orders import OrderState
from duty_engine.storage import Archive


def planner_of(golden_day: GoldenDay) -> Planner:
    return golden_day.planner


def decision_text(
    pool_version: str, tag: str, hh_mm_ss: str, rows: list[tuple[str, str, str, str]]
) -> str:
    """按 plan §4.5.1 生成一份 DECISION 原文。"""
    lines = [
        f"# DECISION · {DAY.isoformat()} · {tag}",
        f"as_of: {DAY.isoformat()}T{hh_mm_ss}+08:00",
        f"pool_version: {pool_version}",
    ]
    for code, name, stance, reason in rows:
        lines += [
            "",
            f"## {code} {name}",
            f"stance: {stance}",
            "confidence: high",
            "dd_ref: 无背调",
            "evidence:",
            '  - "[quote_snapshot@2026-09-16] 样本"',
            f"reasoning: {reason}",
        ]
    return "\n".join(lines) + "\n"


def denied(replies: list[str]) -> list[str]:
    return [
        reply for reply in replies if "permission" in reply.lower() or "denied" in reply.lower()
    ]


def test_decision_no_cross_read(golden_day: GoldenDay) -> None:
    """1 号实例想抄 2 号原文：被文件系统权限拒绝，读池子仍然合法。"""
    run = planner_of(golden_day).run_role(
        decision.spec_for_tag("gpt"), DAY, ask="看看别人怎么写的", cassette="decision-gpt-probe"
    )
    assert len(denied(run.replies)) == 2, run.replies
    assert any("平安银行" in reply for reply in run.replies), "池子必须可读"


def test_review_cannot_read_decision(golden_day: GoldenDay) -> None:
    run = planner_of(golden_day).run_role(
        review.SPEC, DAY, ask="先看看决策原文", cassette="review-probe"
    )
    assert len(denied(run.replies)) == 2, run.replies
    assert any("target_bps" in reply for reply in run.replies), "引擎锁定计划必须可读"


def test_decision_late_submission_not_counted(golden_day: GoldenDay) -> None:
    planner = planner_of(golden_day)
    planner.archive.write_once(
        DAY,
        "DECISION-late.md",
        decision_text(
            golden_day.pool.pool_version,
            "late",
            "08:51:00",
            [(HELD_CODE, "贵州茅台", "清仓", "尾盘无异动 [quote_snapshot@2026-09-16]。")],
        ),
    )
    collected = planner.collect_decisions(DAY, golden_day.pool, ("late",))
    assert collected[0].voided and "迟交" in collected[0].void_reason
    assert not planner.archive.exists(DAY, "DECISION-late.md")
    assert planner.archive.exists(DAY, "DECISION-late.md.REJECTED")
    assert any(alert["kind"] == "sig001" for alert in planner.store.alerts())


def test_sig001_hits_void_whole_file_and_rename(golden_day: GoldenDay) -> None:
    """命中即整份作废：同一份里那条合法的 stance 也不再计票。"""
    planner = planner_of(golden_day)
    planner.archive.write_once(
        DAY,
        "DECISION-dirty.md",
        decision_text(
            golden_day.pool.pool_version,
            "dirty",
            "08:40:00",
            [
                (HELD_CODE, "贵州茅台", "清仓", "先卖掉 3 手 [quote_snapshot@2026-09-16]。"),
                ("000001", "平安银行", "建仓", "基本面改善 [quote_snapshot@2026-09-16]。"),
            ],
        ),
    )
    collected = planner.collect_decisions(DAY, golden_day.pool, ("dirty",))
    assert collected[0].voided and "SIG-001" in collected[0].void_reason
    assert planner.archive.exists(DAY, "DECISION-dirty.md.REJECTED")
    rejected = _rejected(planner.archive, DAY, "DECISION-dirty.md")
    assert "stance: 清仓" in rejected and "stance: 建仓" in rejected, "整份作废不是删行"
    plan = engine_lock_plan(collected, golden_day.pool, golden_day.pool.locked_at)
    assert all(target.votes == 0 for target in plan.targets)


def test_malformed_decision_is_voided(golden_day: GoldenDay) -> None:
    planner = planner_of(golden_day)
    planner.archive.write_once(
        DAY,
        "DECISION-broken.md",
        f"# DECISION · {DAY.isoformat()} · broken\n"
        f"as_of: {DAY.isoformat()}T08:40:00+08:00\n\n"
        f"## {HELD_CODE} 贵州茅台\nstance: 清仓\nconfidence: high\n",
    )
    collected = planner.collect_decisions(DAY, golden_day.pool, ("broken",))
    assert collected[0].voided and "格式不合格" in collected[0].void_reason


def test_intraday_forbids_new_code(golden_day: GoldenDay) -> None:
    planner = planner_of(golden_day)
    budget = IntradayBudget(2, 4)
    granted, reason = planner.intraday_proposal(golden_day.plan, budget, "002456")
    assert not granted and "新码" in reason
    assert budget.used_global == 0
    assert any(alert["kind"] == "offpool" for alert in planner.store.alerts())
    assert planner.intraday_proposal(golden_day.plan, budget, HELD_CODE)[0]


def test_intraday_cooldown_limits(golden_day: GoldenDay) -> None:
    planner = planner_of(golden_day)
    budget = IntradayBudget(2, 4)
    results = [planner.intraday_proposal(golden_day.plan, budget, HELD_CODE) for _ in range(3)]
    assert [granted for granted, _ in results] == [True, True, False]
    assert "同标的" in results[2][1]
    assert planner.intraday_proposal(golden_day.plan, budget, "000001")[0]
    assert planner.intraday_proposal(golden_day.plan, budget, "300750")[0]
    fourth, reason = planner.intraday_proposal(golden_day.plan, budget, "000001")
    assert not fourth and "全局" in reason


def test_screener_holdings_forced_in(golden_day: GoldenDay) -> None:
    """就算选股把持仓股漏了，池锁定也必须把它拽回来——这条不依赖提示词。"""
    planner = planner_of(golden_day)
    planner.archive.path(DAY, "CANDIDATES.md").write_text(
        f"# CANDIDATES · {DAY.isoformat()}\n\n## 000001 平安银行\nheld: false\ndd_ref: 无背调\n",
        encoding="utf-8",
    )
    pool = planner.lock_pool(DAY)
    assert HELD_CODE in pool.codes
    assert set(pool.codes) == {HELD_CODE, "000001"}


def test_evidence_appended_per_tool_call(golden_day: GoldenDay) -> None:
    lines = planner_of(golden_day).archive.read(DAY, "EVIDENCE-screener.md").splitlines()
    assert len(lines) == 5, lines
    assert all("→ adopted" in line for line in lines)
    assert all(line.startswith("2026-09-16T07:55") for line in lines)


def test_quota_exhausted_forces_low_info(planner: Planner) -> None:
    """超配额不许编：10 次 iFinD 调用里后 2 次被拒，角色只能带着 LOW_INFO 出池。"""
    run = planner.run_role(screener.SPEC, DAY, ask="继续查", cassette="screener-exhausted")
    assert run.low_info
    lines = planner.archive.read(DAY, "EVIDENCE-screener.md").splitlines()
    assert len([line for line in lines if "配额耗尽" in line]) == 2
    assert len([line for line in lines if "→ adopted" in line]) == 8
    assert "low_info: true" in planner.archive.read(DAY, "CANDIDATES.md")


def test_intent_guard_rejects_non_user_turn(golden_day: GoldenDay) -> None:
    planner = planner_of(golden_day)
    ledger = TurnLedger(planner.settings.turn_ledger_path())
    order = golden_day.plan.orders[0]
    scheduled = ledger.record("请确认这笔单", origin="cron", at=planner.now)
    with pytest.raises(UnverifiedIntent):
        planner.confirm(order, scheduled.intent_id)
    human = ledger.record("确认 000001 这笔", origin="user", at=planner.now)
    moved = planner.confirm(order, human.intent_id)
    assert moved.state is OrderState.QUEUED
    assert moved.intent_id == human.intent_id


def test_watch_zero_attribution(golden_day: GoldenDay) -> None:
    planner = planner_of(golden_day)
    text = planner.archive.read(DAY, "INTRADAY.md")
    for word in ("因为", "由于", "导致", "消息", "传闻", "建议", "应该"):
        assert word not in text, word
    evidence = planner.archive.read(DAY, "EVIDENCE-watch.md")
    assert "ifind_panel" not in evidence and "vertical_search" not in evidence


def test_golden_day_covers_every_role(golden_day: GoldenDay) -> None:
    assert {run.role for run in golden_day.runs} == {
        "screener",
        "news",
        "diligence",
        "decision-gpt",
        "decision-claude",
        "decision-glm",
        "director",
        "review",
        "watch",
    }


def test_builtin_write_tools_are_switched_off() -> None:
    """内置写类工具（含 `delete`）整体禁用，交卷只能走只追加通道。"""
    rules = [rule for rule in permissions_for(screener.SPEC) if "write" in rule.operations]
    assert [(rule.mode, rule.paths) for rule in rules] == [("deny", ["/**"])]


def test_golden_day_pool_matches_fixture_universe(golden_day: GoldenDay) -> None:
    assert set(golden_day.pool.codes) <= set(GOLDEN_CODES)
    assert golden_day.plan.pool_version == golden_day.pool.pool_version


def _rejected(archive: Archive, day: date, name: str) -> str:
    return archive.path(day, f"{name}.REJECTED").read_text(encoding="utf-8")
