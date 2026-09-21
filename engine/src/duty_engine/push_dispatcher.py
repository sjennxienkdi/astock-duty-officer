"""四类卡片的事件分发（plan §9 / §7）。渲染模板在 app 侧，webhook 未配置时落 outbox。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Protocol

from duty_engine.clock import ensure_shanghai
from duty_engine.storage import require_int

MORNING_DECISION = "morning_decision"
INTRADAY_PROPOSAL = "intraday_proposal"
DAILY_SUMMARY = "daily_summary"
ALERT_CARD = "alert"

# plan §9 上限列：1/日、≤4/日、1/日、不限
CARD_KINDS = (MORNING_DECISION, INTRADAY_PROPOSAL, DAILY_SUMMARY, ALERT_CARD)
CARD_DAILY_LIMITS: Mapping[str, int | None] = {
    MORNING_DECISION: 1,
    INTRADAY_PROPOSAL: 4,
    DAILY_SUMMARY: 1,
    ALERT_CARD: None,
}


class Renderer(Protocol):
    """把事件渲染成人看的卡片正文。模板属于 app 侧，引擎不知道样式。"""

    def render(self, event: PushEvent) -> str: ...


@dataclass(frozen=True)
class PushEvent:
    """一条待分发事件。`numbers` 必须全部来自引擎。"""

    kind: str
    at: datetime
    subject: str
    numbers: Mapping[str, int]
    comments: tuple[str, ...] = ()
    confirm_url: str = ""

    def __post_init__(self) -> None:
        if self.kind not in CARD_KINDS:
            raise ValueError(f"未知卡片类型: {self.kind}")
        ensure_shanghai(self.at)
        for name, value in self.numbers.items():
            require_int(f"numbers[{name}]", value)


@dataclass(frozen=True)
class DispatchResult:
    """分发结果。"""

    channel: str
    path: str = ""
    reason: str = ""


@dataclass
class PushDispatcher:
    """限次 + 落盘/推送二选一。引擎不渲染，只分发。"""

    outbox_dir: Path
    renderer: Renderer
    webhook_url: str = ""
    _sent: dict[tuple[date, str], int] = field(default_factory=dict, repr=False)

    def dispatch(
        self, event: PushEvent, *, poster: Callable[[str, str], None] | None = None
    ) -> DispatchResult:
        """按 §9 上限分发；超限或未配置 webhook 时落 `outbox/{ts}.md`。"""
        day = ensure_shanghai(event.at).date()
        limit = CARD_DAILY_LIMITS[event.kind]
        sent = self._sent.get((day, event.kind), 0)
        if limit is not None and sent >= limit:
            return DispatchResult(channel="skipped", reason=f"{event.kind} 当日已达 {limit} 次上限")
        self._sent[(day, event.kind)] = sent + 1
        body = self.renderer.render(event)
        if not self.webhook_url:
            return DispatchResult(channel="outbox", path=str(self._write_outbox(event, body)))
        if poster is None:
            return DispatchResult(channel="outbox", path=str(self._write_outbox(event, body)))
        poster(self.webhook_url, body)
        return DispatchResult(channel="webhook")

    def _outbox_name(self, event: PushEvent) -> str:
        return f"{ensure_shanghai(event.at).strftime('%Y%m%dT%H%M%S')}-{event.kind}.md"

    def _write_outbox(self, event: PushEvent, body: str) -> Path:
        self.outbox_dir.mkdir(parents=True, exist_ok=True)
        target = self.outbox_dir / self._outbox_name(event)
        target.write_text(body.rstrip("\n") + "\n", encoding="utf-8", newline="\n")
        return target
