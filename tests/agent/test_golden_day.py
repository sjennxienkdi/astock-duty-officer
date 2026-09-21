"""金日子回放（plan §12 M3 验收）：喂 fixtures，跑完整天，断言三类产物字段齐全。"""

from __future__ import annotations

from pathlib import Path

from conftest import DAY, EXAMPLES, FRESH_CODE, GOLDEN_CODES, HELD_CODE, GoldenDay, run_golden_day
from duty_agent.config import Settings
from duty_agent.planner import build_planner, parse_candidates
from duty_engine.aggregate import Stance
from duty_engine.freeze import parse_decision
from duty_engine.storage import Archive


def test_golden_day_replay(golden_day: GoldenDay) -> None:
    archive = golden_day.planner.archive

    candidates = parse_candidates(archive.read(DAY, "CANDIDATES.md"))
    assert {p.code for p in candidates} == set(GOLDEN_CODES)
    assert all(p.code and p.name for p in candidates)
    assert any(p.held for p in candidates), "持仓股必须出现在池里"
    assert all(p.dd_ref for p in candidates)

    for tag in ("gpt", "claude", "glm"):
        decision = parse_decision(archive.read(DAY, f"DECISION-{tag}.md"))
        assert decision.pool_version == golden_day.pool.pool_version
        assert decision.entries, tag
        for entry in decision.entries:
            assert entry.stance in set(Stance)
            assert entry.confidence in {"high", "medium", "low"}
            assert entry.evidence and entry.reasoning

    morning = archive.read(DAY, "MORNING.md")
    for field in (
        "pool_version",
        "locked_at",
        "portfolio_cents",
        "target_bps",
        "protect_trigger_cents",
    ):
        assert field in morning, field


def test_golden_day_pool_and_plan(golden_day: GoldenDay) -> None:
    assert set(golden_day.pool.codes) == {FRESH_CODE, HELD_CODE, "300750"}
    assert any(code == "002456" for code, _ in golden_day.pool.dropped)
    assert golden_day.plan.voided_tags == ()
    assert golden_day.plan.absent_tags == ()
    assert len(golden_day.plan.orders) == 1
    order = golden_day.plan.orders[0]
    assert (order.code, order.side, str(order.state)) == (FRESH_CODE, "buy", "approved")


def test_golden_day_conflict_falls_back_to_neutral(golden_day: GoldenDay) -> None:
    target = next(t for t in golden_day.plan.targets if t.code == "300750")
    assert target.conflict and target.stance is Stance.HOLD and target.votes == 3


def test_golden_day_writes_every_role_archive(golden_day: GoldenDay) -> None:
    archive = Archive(golden_day.planner.settings.results_dir)
    for name in (
        "PACK.md",
        "POOL-DRAFT.md",
        "CANDIDATES.md",
        "EVENT-INDEX.md",
        "MORNING.md",
        "PLAN.md",
        "CROSS_EXAM.md",
        "REVIEW-deepseek.md",
        "INTRADAY.md",
        "INTRADAY-DECISION-gpt.md",
        "NOON.md",
        "SUMMARY.md",
        "EVENTS-POSITIONS.md",
        "ALERT.md",
    ):
        assert archive.exists(DAY, name), name
    assert archive.exists(DAY, "DD/300750/2026-09-15.md")
    assert archive.exists(DAY, "EVIDENCE-screener.md")


def test_golden_day_triggers_intraday_alert(golden_day: GoldenDay) -> None:
    assert "300750" in golden_day.triggered
    text = golden_day.planner.archive.read(DAY, "ALERT.md")
    assert "kind=volatility 300750" in text


def test_golden_day_dispatches_four_cards(golden_day: GoldenDay) -> None:
    """四类卡片都走 outbox（webhook 未配置），且都是限次内的第一次。"""
    kinds = [kind for kind, _ in golden_day.cards]
    assert {"morning", "alert", "proposal", "summary"} == set(kinds)
    assert all(channel == "outbox" for _, channel in golden_day.cards)
    bodies = [
        path.read_text(encoding="utf-8")
        for path in golden_day.planner.settings.outbox_dir.glob("*.md")
    ]
    assert len(bodies) == len(kinds)
    assert any("# 早盘决策卡" in body for body in bodies)
    assert any("# 波动提案" in body for body in bodies)
    assert any("# 日报" in body for body in bodies)
    assert any("# 告警" in body for body in bodies)


def test_golden_day_morning_card_separates_engine_from_comments(golden_day: GoldenDay) -> None:
    morning = next(
        path.read_text(encoding="utf-8")
        for path in golden_day.planner.settings.outbox_dir.glob("*morning_decision.md")
    )
    assert "## 引擎判定（聚合后）" in morning
    assert "## 引擎数字" in morning
    assert "极差≥2 已回落中性" in morning
    assert "移池淘汰 002456" in morning
    assert "## 评论（agent 判断，不构成指令）" in morning
    assert "卡片内没有确认按钮" in morning


def _run_into(root: Path) -> dict[str, bytes]:
    settings = Settings(
        display_mode=True,
        results_dir=root / "results",
        examples_dir=EXAMPLES,
        db_path=root / "duty.sqlite3",
        outbox_dir=root / "outbox",
        portfolio_cents=100_000_000,
    )
    run_golden_day(build_planner(settings, DAY))
    daily = root / "results" / "daily" / DAY.isoformat()
    files = sorted(p for p in daily.rglob("*") if p.is_file())
    return {p.relative_to(daily).as_posix(): p.read_bytes() for p in files}


def test_golden_day_is_byte_reproducible(tmp_path: Path) -> None:
    """两次独立回放必须逐字节一致——否则「可回放」这句话不成立。"""
    first = _run_into(tmp_path / "a")
    second = _run_into(tmp_path / "b")
    assert first.keys() == second.keys()
    drift = [name for name in first if first[name] != second[name]]
    assert not drift, f"回放漂移: {drift}"


def test_examples_match_golden_day_replay(tmp_path: Path) -> None:
    """仓库里的 examples 必须等于当前代码跑出来的结果，防止文档与实现分家。"""
    produced = _run_into(tmp_path / "run")
    committed = {
        p.relative_to(EXAMPLES).as_posix(): p.read_bytes()
        for p in sorted(EXAMPLES.rglob("*"))
        if p.is_file() and "fixtures" not in p.relative_to(EXAMPLES).parts
    }
    assert produced.keys() == committed.keys()
    drift = [name for name in produced if produced[name] != committed[name]]
    assert not drift, f"examples 与重跑结果不一致: {drift}"
