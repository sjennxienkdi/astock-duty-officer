"""决策 Agent（plan §4.5）：多实例，唯一能变订单的判断者。"""

from __future__ import annotations

from duty_agent.agents import RoleSpec, prompt_for


def prompt_for_tag(tag: str) -> str:
    """某个决策实例的系统提示词。"""
    return prompt_for(
        f"decision-{tag}",
        f"""你是第 {tag} 号决策实例。
职责：盘前 08:20–08:44 对池内任意标的出 stance（清仓/减仓/持有/建仓/加仓 五词之一）。
硬规则：
- 禁互读：其他实例的 DECISION-*.md 你看不到，也不许猜。独立判断才有对垒价值。
- 08:44 之后交卷不计票。
- 盘中窗口（INTRADAY-DECISION）仅限已持仓或已冻结未成交的标的，禁止引入新码。
- 盘中冷却：同标的 ≤2 次/日、全局 ≤4 次/日，超限系统只写 ALERT，你不得继续提案。
- DD 报告只是参考，不是否决条件；`无背调` 不等于不能判断，但必须打 LOW_INFO。
聚合在引擎侧完成，你自己不做聚合、不算仓位。""",
    )


def spec_for_tag(tag: str) -> RoleSpec:
    """决策实例的角色规格：只允许读自己那一份 DECISION（自己的产物由引擎自动放行）。"""
    return RoleSpec(
        role=f"decision-{tag}",
        describe=f"盘前/盘中决策实例 {tag}，禁互读",
        outputs=(f"DECISION-{tag}.md", f"INTRADAY-DECISION-{tag}.md"),
        tools=("quote_snapshot", "ifind_panel", "vertical_search", "gm_kline", "recall"),
        read_deny=("/DECISION-*.md", "/INTRADAY-DECISION-*.md", "/REVIEW-*.md", "/CROSS_EXAM.md"),
        prompt=prompt_for_tag(tag),
    )
