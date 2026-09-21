"""卡片模板（plan §9）：数字一律引擎给，agent 文字一律标「评论」，卡片不含确认按钮。"""

from __future__ import annotations

from duty_engine.push_dispatcher import (
    ALERT_CARD,
    DAILY_SUMMARY,
    INTRADAY_PROPOSAL,
    MORNING_DECISION,
    PushEvent,
)

TITLE_ZH = {
    MORNING_DECISION: "早盘决策卡",
    INTRADAY_PROPOSAL: "波动提案",
    DAILY_SUMMARY: "日报",
    ALERT_CARD: "告警",
}


class CardRenderer:
    """把引擎事件渲染成企业微信 markdown。只排版，不计算。"""

    def render(self, event: PushEvent) -> str:
        """生成卡片正文。"""
        lines = [f"# {TITLE_ZH[event.kind]} · {event.at.date().isoformat()}", "", event.subject, ""]
        if event.facts:
            lines += ["## 引擎判定（聚合后）", *[f"- {fact}" for fact in event.facts], ""]
        lines += ["## 引擎数字"]
        lines += [f"- {name}: {value}" for name, value in sorted(event.numbers.items())] or ["- 无"]
        if event.comments:
            lines += ["", "## 评论（agent 判断，不构成指令）"]
            lines += [f"- {text}" for text in event.comments]
        if event.confirm_url:
            lines += [
                "",
                f"确认页：{event.confirm_url}",
                "",
                "卡片内没有确认按钮，请在确认页完成放行。",
            ]
        return "\n".join(lines).rstrip() + "\n"
