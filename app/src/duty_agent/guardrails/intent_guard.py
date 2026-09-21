"""intent 守卫（plan §5.6）：只有真实用户轮次能放行订单。"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from duty_engine.clock import ensure_shanghai

# 只有 user 算真实轮次；其余一律不算（定时任务、子代理回传、页面/微信里的「请确认」文本）
ORIGINS = ("user", "cron", "subagent", "wecom", "page_text")
TRUSTED_ORIGIN = "user"


class UnverifiedIntent(PermissionError):
    """confirm 请求没带真实用户轮次。"""


@dataclass(frozen=True)
class Turn:
    """一条轮次记录。"""

    intent_id: str
    at: datetime
    origin: str
    text: str


def new_intent_id() -> str:
    """生成一个 intent_id。"""
    return secrets.token_hex(8)


@dataclass
class TurnLedger:
    """只追加的用户轮次账本（JSONL）。"""

    path: Path

    def record(self, text: str, *, origin: str, at: datetime) -> Turn:
        """登记一条轮次；`origin` 决定是否可信。"""
        if origin not in ORIGINS:
            raise ValueError(f"未知轮次来源: {origin}")
        turn = Turn(new_intent_id(), ensure_shanghai(at), origin, text)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(turn.__dict__, ensure_ascii=False, default=str) + "\n")
        return turn

    def turns(self) -> tuple[Turn, ...]:
        if not self.path.is_file():
            return ()
        rows = [
            json.loads(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return tuple(
            Turn(r["intent_id"], datetime.fromisoformat(r["at"]), r["origin"], r["text"])
            for r in rows
        )

    def is_real_user_turn(self, intent_id: str) -> bool:
        return any(t.intent_id == intent_id and t.origin == TRUSTED_ORIGIN for t in self.turns())


def verify(ledger: TurnLedger, intent_id: str) -> Turn:
    """校验 intent_id 来自真实用户轮次，否则抛 `UnverifiedIntent`。"""
    for turn in ledger.turns():
        if turn.intent_id == intent_id and turn.origin == TRUSTED_ORIGIN:
            return turn
    raise UnverifiedIntent(f"intent_id {intent_id!r} 不在真实用户轮次记录中，拒绝放行")
