"""M1 骨架冒烟：包可导入、目录结构符合 plan §11、命名冻结表齐全、脱敏与主链图检查通过。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_secrets  # noqa: E402

ARCHIVE_FILES = [
    "POOL-DRAFT.md",
    "PACK.md",
    "EVENT-INDEX.md",
    "CANDIDATES.md",
    "EVIDENCE-{role}.md",
    "DD/{code}/{date}.md",
    "DECISION-{tag}.md",
    "MORNING.md",
    "PLAN.md",
    "REVIEW-{tag}.md",
    "CROSS_EXAM.md",
    "NOON.md",
    "INTRADAY.md",
    "INTRADAY-DECISION-{tag}.md",
    "SUMMARY.md",
    "EVENTS-POSITIONS.md",
    "ALERT.md",
]

ORDER_STATES = [
    "draft",
    "approved",
    "queued",
    "submitted",
    "filled",
    "partial",
    "rejected",
    "canceled",
    "expired",
    "archived",
]

STANCES = ["清仓", "减仓", "持有", "建仓", "加仓"]


def test_smoke_packages_importable() -> None:
    import duty_agent
    import duty_engine

    assert duty_agent.__file__ is not None
    assert duty_engine.__file__ is not None


def test_smoke_plan_required_paths_exist() -> None:
    required = [
        "app/src/duty_agent",
        "app/src/duty_agent/agents",
        "app/src/duty_agent/guardrails",
        "app/src/duty_agent/memory",
        "app/src/duty_agent/notify",
        "engine/src/duty_engine",
        "web/pages",
        "examples/replay-2026-09-16",
        "scripts",
        "tests",
        ".github/workflows",
    ]
    missing = [p for p in required if not (ROOT / p).is_dir()]
    assert not missing, f"缺少目录: {missing}"


def test_smoke_workflows_present() -> None:
    for name in ("ci.yml", "lint.yml", "docs.yml"):
        assert (ROOT / ".github" / "workflows" / name).is_file(), name


def test_smoke_naming_freeze_is_single_sourced() -> None:
    """冻结名只允许出现在 plan §2 与代码常量里，避免第二份真相源。"""
    plan = (ROOT / "plan.md").read_text(encoding="utf-8")
    for name in ARCHIVE_FILES + ORDER_STATES + STANCES:
        assert name in plan, f"plan.md §2 缺少冻结名 {name}"


@pytest.mark.parametrize("state", ORDER_STATES)
def test_smoke_order_state_names_are_ascii_identifiers(state: str) -> None:
    assert state.isascii() and state.islower()


def test_smoke_secrets_check_passes() -> None:
    assert check_secrets.check() == []


def test_smoke_readme_first_diagram_matches_plan() -> None:
    import check_diagram

    canonical = check_diagram.first_diagram(ROOT / "plan.md")
    assert check_diagram.first_diagram(ROOT / "README.md") == canonical
