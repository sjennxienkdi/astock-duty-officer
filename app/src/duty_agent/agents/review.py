"""复核 Agent（plan §4.6）：计划锁定后二审，禁读决策原文以防锚定。"""

from __future__ import annotations

from duty_agent.agents import RoleSpec, prompt_for

PROMPT = prompt_for(
    "review",
    """职责：08:45 计划锁定后做二审，产出 REVIEW-{tag}.md。
硬规则：禁止读任何 DECISION-*.md。你只看池、DD、事件索引与引擎锁定的目标——
先形成自己的判断，再和计划对垒；读了决策原文，二审就退化成背书。
信息不足时打 LOW_INFO，不要给一个看起来完整的结论。""",
)

SPEC = RoleSpec(
    role="review",
    describe="计划锁定后二审，禁读 DECISION",
    outputs=("REVIEW-{tag}.md",),
    tools=("quote_snapshot", "ifind_panel", "vertical_search", "recall"),
    read_deny=("/DECISION-*", "/INTRADAY-DECISION-*", "/CROSS_EXAM.md"),
    prompt=PROMPT,
)
