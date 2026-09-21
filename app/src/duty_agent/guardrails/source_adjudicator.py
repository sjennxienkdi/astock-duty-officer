"""取证与采信（plan §5.3）：取证自由，进结论的每条证据必须有来源、时间戳且未过期。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from duty_engine.clock import ensure_shanghai, is_trading_day
from duty_engine.storage import Archive

# 白名单工具（plan §5.3），`recall` 由记忆层提供
SOURCE_WHITELIST = (
    "quote_snapshot",
    "ifind_panel",
    "vertical_search",
    "tianyancha_flags",
    "gm_kline",
    "recall",
)

# 资讯类证据的时效门槛（交易日）
STALE_AFTER_TRADING_DAYS = 3

CITATION = re.compile(r"\[([a-z_]+)@([0-9]{4}-[0-9]{2}-[0-9]{2})(?:T[0-9:.+\-Z]+)?\]")
# 只有资讯类证据受 3 个交易日时效门槛约束。KB 召回的结题卡与结论档本身就是跨日语义，
# 对它们套时效等于否认 §6 的立论，因此 recall 不在这里过期，只查白名单。
NEWS_TOOLS = frozenset({"vertical_search"})
_REASONING = re.compile(r"^reasoning:\s*(.*)$")


def trading_days_between(earlier: date, later: date) -> int:
    """两个日期之间的间隔交易日数（不含起始日，按工作日计）。"""
    if later < earlier:
        raise ValueError(f"later {later} 早于 earlier {earlier}")
    span = (later - earlier).days
    return sum(
        1 for offset in range(1, span + 1) if is_trading_day(earlier + timedelta(days=offset))
    )


@dataclass
class QuotaMeter:
    """一次会话的配额计数（plan §4.2）。"""

    limits: dict[str, int]
    used: dict[str, int] = field(default_factory=dict)

    def consume(self, tool: str) -> bool:
        """占用一次配额，耗尽返回 False。"""
        limit = self.limits.get(tool)
        if limit is None:
            return True
        if self.used.get(tool, 0) >= limit:
            return False
        self.used[tool] = self.used.get(tool, 0) + 1
        return True

    def left(self, tool: str) -> int:
        return self.limits.get(tool, 0) - self.used.get(tool, 0)


@dataclass
class Adjudicator:
    """采信门槛：把一次工具调用判成 adopted / rejected。"""

    today: date
    quota: QuotaMeter
    problems: list[str] = field(default_factory=list)

    def judge(self, tool: str, *, stamp: datetime, stale_checked: bool = True) -> tuple[str, str]:
        """返回 `(verdict, reason)`，verdict ∈ {adopted, rejected}。"""
        if tool not in SOURCE_WHITELIST:
            return "rejected", "非白名单来源"
        if not self.quota.consume(tool):
            return "rejected", "配额耗尽"
        if stale_checked and tool in NEWS_TOOLS:
            age = trading_days_between(ensure_shanghai(stamp).date(), self.today)
            if age > STALE_AFTER_TRADING_DAYS:
                return "rejected", f"资讯类证据已 {age} 个交易日，超时效门槛"
        return "adopted", "ok"


@dataclass
class EvidenceLog:
    """`EVIDENCE-{role}.md`：每次工具调用追加一行。"""

    role: str
    archive: Archive
    day: date

    def append(self, at: datetime, tool: str, query: str, verdict: str, reason: str) -> None:
        line = f"{at.isoformat()} {tool} {query} → {verdict} {reason}"
        self.archive.append(self.day, f"EVIDENCE-{self.role}.md", line)

    def lines(self) -> list[str]:
        if not self.archive.exists(self.day, f"EVIDENCE-{self.role}.md"):
            return []
        return self.archive.read(self.day, f"EVIDENCE-{self.role}.md").splitlines()


def audit_reasoning(text: str, today: date) -> tuple[str, ...]:
    """结论里的 `reasoning:` 必须逐条带白名单引用且在时效内；返回问题清单。"""
    problems: list[str] = []
    for line in text.splitlines():
        match = _REASONING.match(line.strip())
        if match is None:
            continue
        body = match.group(1)
        citations = CITATION.findall(body)
        if not citations:
            problems.append(f"结论缺 [source@time] 引用: {body[:24]}")
            continue
        for source, stamp in citations:
            if source not in SOURCE_WHITELIST:
                problems.append(f"引用来源不在白名单: {source}")
            elif source in NEWS_TOOLS:
                age = trading_days_between(date.fromisoformat(stamp), today)
                if age > STALE_AFTER_TRADING_DAYS:
                    problems.append(f"引用已 {age} 个交易日，超时效门槛: {source}@{stamp}")
    return tuple(problems)
