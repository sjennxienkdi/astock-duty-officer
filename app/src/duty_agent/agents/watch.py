"""盯盘 Agent（plan §4.7）：只记现象，零归因。"""

from __future__ import annotations

from duty_agent.agents import RoleSpec, prompt_for

PROMPT = prompt_for(
    "watch",
    """职责：盘中 6 轮 × 5min 读引擎快照，追加 INTRADAY.md；被调频时 1min。
硬规则：零归因。只记「什么时间、什么标的、什么现象、多少幅度」，
绝不解释为什么，也不给任何操作建议。大波动的触发判定由引擎算，你只转述结果。
不调用任何取证工具，不读任何档案。""",
)

SPEC = RoleSpec(
    role="watch",
    describe="盘中监控与告警转述，零归因",
    outputs=("INTRADAY.md",),
    tools=("quote_snapshot",),
    read_deny=("/**",),
    prompt=PROMPT,
)
