"""SIG-001：LLM 产物里出现数量/价格/仓位即整份作废（plan §5.4）。"""

from __future__ import annotations

import re

# 四条规则。plan §5.4 的 `\b` 在中文语境下不成立（`股` 与后续汉字都是 \w），
# 一律换成「后面不是数字」的负向前看，详见 DECISION-LOG。
PATTERNS: dict[str, re.Pattern[str]] = {
    "数量/手数": re.compile(r"\d+\s*(?:手|股)(?![0-9])"),
    "价格/限价": re.compile(r"(?:限价|目标价|止损价|买入价|卖出价)\s*[:：]?\s*\d+(?:\.\d+)?"),
    "仓位/金额": re.compile(r"(?:仓位|敞口|金额|预算)\s*[:：]?\s*\d+(?:\.\d+)?\s*(?:%|万|元|bps)?"),
    "百分比仓位": re.compile(r"仓\s*\d+(?:\.\d+)?\s*%"),
}


def scan(text: str) -> tuple[str, ...]:
    """返回命中的规则名；命中任一即整份作废，不是删行。"""
    return tuple(name for name, pattern in PATTERNS.items() if pattern.search(text))


def hits(text: str) -> tuple[str, ...]:
    """返回命中的原文片段，用于写 ALERT 与复盘。"""
    found: list[str] = []
    for pattern in PATTERNS.values():
        found.extend(match.group(0).strip() for match in pattern.finditer(text))
    return tuple(found)
