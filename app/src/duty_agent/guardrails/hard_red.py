"""背调七条与硬雷标记（plan §4.4 / §5.1）。diligence 无否决权，只打标记。"""

from __future__ import annotations

import re

from duty_engine.freeze import HARD_RED_FLAGS

# 检查项固定七条，顺序与 DD 报告一致
DD_CHECKS = ("质押", "失信", "诉讼", "开庭", "终本", "解禁", "对外担保")

_FLAG_MAP: dict[str, tuple[str, tuple[str, ...]]] = {
    "失信": ("credit_default", ("失信", "命中")),
    "终本": ("terminated_execution", ("终本", "命中")),
    "诉讼": ("case_investigation", ("立案调查",)),
    "质押": ("pledge_margin_line", ("爆仓线",)),
}

_LINE = re.compile(r"^-\s*(\S+)\s*[:：]\s*(.+)$")
_NEGATIONS = ("未", "无", "不", "尚未")


def _negated(value: str, keyword: str) -> bool:
    """关键词前 3 字里出现否定词即视为未命中，别把「未触及爆仓线」读成命中。"""
    index = value.find(keyword)
    if index < 0:
        return True
    return any(negation in value[max(0, index - 3) : index] for negation in _NEGATIONS)


def scan_dd(text: str) -> frozenset[str]:
    """从 DD 报告正文提取硬雷标记，输出一律落在引擎冻结的四类里。"""
    flags: set[str] = set()
    for line in text.splitlines():
        match = _LINE.match(line.strip())
        if match is None:
            continue
        check, value = match.group(1), match.group(2)
        mapped = _FLAG_MAP.get(check)
        if mapped is None:
            continue
        flag, keywords = mapped
        if any(keyword in value and not _negated(value, keyword) for keyword in keywords):
            flags.add(flag)
    return frozenset(flags & set(HARD_RED_FLAGS))


def missing_checks(text: str) -> tuple[str, ...]:
    """返回报告里缺失的检查项，七条不齐即为无效报告。"""
    present = {
        match.group(1)
        for line in text.splitlines()
        if (match := _LINE.match(line.strip())) is not None
    }
    return tuple(check for check in DD_CHECKS if check not in present)


def render_dd(code: str, name: str, day: str, findings: dict[str, str], note: str = "") -> str:
    """生成 DD 报告正文，七条齐全。"""
    missing = set(DD_CHECKS) - set(findings)
    if missing:
        raise ValueError(f"DD 检查项不齐: {sorted(missing)}")
    lines = [f"# DD · {code} {name} · {day}", ""]
    lines += [f"- {check}: {findings[check]}" for check in DD_CHECKS]
    flags = sorted(scan_dd("\n".join(lines)))
    lines += ["", f"hard_red: {'true' if flags else 'false'}", f"flags: {', '.join(flags) or '无'}"]
    if note:
        lines += ["", note]
    return "\n".join(lines) + "\n"
