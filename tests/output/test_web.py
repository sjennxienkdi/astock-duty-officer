"""值班台五页（plan §8 / §12 M5）：用 AppTest 无头渲染，不起浏览器。"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from conftest import DAY, EXAMPLES, run_golden_day
from duty_agent.config import Settings, get_settings
from duty_agent.planner import build_planner

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "web"))

PAGES = ("pages/board.py", "pages/replay.py", "pages/confirm.py", "pages/kb.py", "pages/evals.py")
ENTRY = ROOT / "web" / "app.py"


@pytest.fixture
def web_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    """把一整天的真实产物落进 tmp，并让页面读到它。"""
    settings = Settings(
        display_mode=True,
        results_dir=tmp_path / "results",
        examples_dir=EXAMPLES,
        db_path=tmp_path / "duty.sqlite3",
        outbox_dir=tmp_path / "outbox",
        kb_index_path=tmp_path / "kb.sqlite3",
        portfolio_cents=100_000_000,
    )
    run_golden_day(build_planner(settings, DAY))
    for key, value in {
        "RESULTS_DIR": str(settings.results_dir),
        "EXAMPLES_DIR": str(settings.examples_dir),
        "DB_PATH": str(settings.db_path),
        "OUTBOX_DIR": str(settings.outbox_dir),
        "KB_INDEX_PATH": str(settings.kb_index_path),
    }.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield settings
    get_settings.cache_clear()


def app(page: str | None = None) -> AppTest:
    """渲染一页。"""
    at = AppTest.from_file(str(ENTRY), default_timeout=20).run()
    return at if page is None else at.switch_page(page).run()


def test_app_entrypoint_renders(web_env: Settings) -> None:
    at = app()
    assert not at.exception
    assert at.title or at.markdown


@pytest.mark.parametrize("page", PAGES)
def test_page_renders_without_exception(web_env: Settings, page: str) -> None:
    at = app(page)
    assert not at.exception, _errors(at)


def test_board_shows_engine_numbers_and_schedule(web_env: Settings) -> None:
    at = app("pages/board.py")
    text = " ".join(str(metric.value) for metric in at.metric)
    assert "2026-09-16-0820" in text
    assert len(at.dataframe) >= 2
    first = at.dataframe[0].value
    assert {"时刻", "定时槽", "执行者", "状态"} <= set(first.columns)
    assert (first["状态"] == "已完成").any()


def test_replay_expands_every_archive_and_evidence(web_env: Settings) -> None:
    at = app("pages/replay.py")
    titles = [str(expanded.label) for expanded in at.expander]
    assert "MORNING.md" in titles
    assert "ALERT.md" in titles
    assert any(label.startswith("EVIDENCE-screener（") for label in titles), titles


def test_confirm_page_creates_user_turn(web_env: Settings) -> None:
    at = app("pages/confirm.py")
    assert at.text_input, "确认页必须有 intent_id 输入框"
    at.text_input[1].set_value("放行 000001").run()
    at.button[0].click().run()
    assert not at.exception, _errors(at)
    assert at.success, "确认应当成功并给出状态"
    assert "queued" in at.success[0].value
    ledger = web_env.turn_ledger_path()
    assert ledger.is_file()
    assert '"origin": "user"' in ledger.read_text(encoding="utf-8")


def test_confirm_rejects_forged_intent(web_env: Settings) -> None:
    at = app("pages/confirm.py")
    at.text_input[0].set_value("定时任务伪造的id").run()
    at.button[0].click().run()
    assert at.error
    assert "拒绝放行" in at.error[0].value
    assert not at.success


def test_kb_page_blocks_bare_query(web_env: Settings) -> None:
    at = app("pages/kb.py")
    at.text_input[0].set_value("缩量过滤为什么保留").run()
    assert at.error
    assert "裸查询" in at.error[0].value
    at.selectbox[0].set_value("experiment").run()
    assert not at.exception, _errors(at)
    assert at.expander, "带 filter 之后必须出召回块"


def test_evals_page_shows_thresholds(web_env: Settings) -> None:
    at = app("pages/evals.py")
    columns = set(at.dataframe[0].value.columns)
    assert {"指标", "值", "来源"} <= columns
    values = at.dataframe[0].value.to_string()
    assert "0.90" in values
    assert any("已关闭" in str(expanded.label) for expanded in at.expander)


def _errors(at: AppTest) -> str:
    return "\n".join(str(element.value) for element in at.exception)
