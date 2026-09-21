"""四类卡片分发与 outbox 回退（plan §9）断言。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from conftest import AT_PLAN_LOCK
from duty_engine.push_dispatcher import (
    ALERT_CARD,
    DAILY_SUMMARY,
    INTRADAY_PROPOSAL,
    MORNING_DECISION,
    DispatchResult,
    PushDispatcher,
    PushEvent,
)


class RecordingRenderer:
    """最小渲染器：引擎测试只验证分发，不验证样式。"""

    def __init__(self) -> None:
        self.seen: list[str] = []

    def render(self, event: PushEvent) -> str:
        self.seen.append(event.kind)
        numbers = " ".join(f"{k}={v}" for k, v in sorted(event.numbers.items()))
        return f"# {event.kind}\n{event.subject}\n{numbers}\n{event.confirm_url}\n"


@pytest.fixture
def renderer() -> RecordingRenderer:
    return RecordingRenderer()


@pytest.fixture
def outbox(tmp_path: Path) -> Path:
    return tmp_path / "outbox"


def event(kind: str, at: datetime | None = None, **numbers: int) -> PushEvent:
    return PushEvent(
        kind=kind,
        at=at or AT_PLAN_LOCK,
        subject="样本标的",
        numbers=numbers or {"portfolio_cents": 100_000_000},
        confirm_url="http://127.0.0.1:8501/confirm",
    )


def test_push_outbox_fallback(outbox: Path, renderer: RecordingRenderer) -> None:
    result = PushDispatcher(outbox, renderer).dispatch(event(MORNING_DECISION))
    assert result == DispatchResult(
        channel="outbox", path=str(outbox / "20260916T084500-morning_decision.md")
    )
    assert Path(result.path).read_text(encoding="utf-8").startswith("# morning_decision")
    assert renderer.seen == [MORNING_DECISION]


def test_push_webhook_used_when_configured(outbox: Path, renderer: RecordingRenderer) -> None:
    posted: list[tuple[str, str]] = []
    dispatcher = PushDispatcher(
        outbox, renderer, webhook_url="https://example.invalid/hook/<token>"
    )
    result = dispatcher.dispatch(
        event(ALERT_CARD), poster=lambda url, body: posted.append((url, body))
    )
    assert result.channel == "webhook"
    assert posted[0][0].endswith("/hook/<token>")
    assert not outbox.exists()


def test_push_respects_daily_limits(outbox: Path, renderer: RecordingRenderer) -> None:
    dispatcher = PushDispatcher(outbox, renderer)
    kinds = [INTRADAY_PROPOSAL] * 5
    results = [dispatcher.dispatch(event(kind)) for kind in kinds]
    assert [r.channel for r in results] == ["outbox"] * 4 + ["skipped"]
    assert "4 次上限" in results[4].reason


def test_push_alerts_are_unlimited(outbox: Path, renderer: RecordingRenderer) -> None:
    dispatcher = PushDispatcher(outbox, renderer)
    results = [dispatcher.dispatch(event(ALERT_CARD)) for _ in range(6)]
    assert all(r.channel == "outbox" for r in results)


def test_push_limits_reset_per_day(outbox: Path, renderer: RecordingRenderer) -> None:
    dispatcher = PushDispatcher(outbox, renderer)
    day_one = AT_PLAN_LOCK
    day_two = AT_PLAN_LOCK.replace(day=17, hour=9)
    assert dispatcher.dispatch(event(MORNING_DECISION, at=day_one)).channel == "outbox"
    assert dispatcher.dispatch(event(MORNING_DECISION, at=day_one)).channel == "skipped"
    assert dispatcher.dispatch(event(MORNING_DECISION, at=day_two)).channel == "outbox"


def test_push_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError):
        event("盘中催单")


def test_push_numbers_must_be_integers() -> None:
    numbers = {"pnl": 1.5}
    with pytest.raises(TypeError):
        PushEvent(kind=DAILY_SUMMARY, at=AT_PLAN_LOCK, subject="s", numbers=numbers)  # type: ignore[arg-type]
