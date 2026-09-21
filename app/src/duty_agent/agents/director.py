"""调度 Agent（plan §4.1）：派活、收卷、写人话文档。"""

from __future__ import annotations

from duty_agent.agents import RoleSpec, prompt_for

PROMPT = prompt_for(
    "director",
    """职责：07:55 开机派活；11:32 / 13:00 / 15:12 稀疏死门；被 ALERT 激活时组织盘中决策窗口。
产出：PLAN.md、NOON.md、SUMMARY.md、EVENTS-POSITIONS.md、CROSS_EXAM.md。
禁区：不产信号、不确认订单、不新增候选、不改触发线、不写任何仓位数字。
引用引擎数字时必须标「引擎」二字；CROSS_EXAM.md 只呈现分歧，不做裁决。
某角色 08:44 未交卷 → 交系统记 ALERT kind=absent，你不重试、不替补。""",
)

SPEC = RoleSpec(
    role="director",
    describe="派活、收卷、写人话文档",
    outputs=("PLAN.md", "NOON.md", "SUMMARY.md", "EVENTS-POSITIONS.md", "CROSS_EXAM.md"),
    tools=(),
    read_deny=(),
    prompt=PROMPT,
)
