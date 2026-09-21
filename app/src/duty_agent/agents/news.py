"""资讯 Agent（plan §4.3）：把采集包读成事件索引，旁挂。"""

from __future__ import annotations

from duty_agent.agents import RoleSpec, prompt_for

PROMPT = prompt_for(
    "news",
    """职责：PACK.md 落盘后即跑，产出 EVENT-INDEX.md，格式为「事件 → 受影响标的 → 来源 → 时间戳」。
禁区：不下结论、不产候选、不当闸门。你是地图不是笼子，下游可以完全不用你。
时效：超过 3 个交易日的资讯一律不进索引。""",
)

SPEC = RoleSpec(
    role="news",
    describe="事件索引，旁挂可读可不用",
    outputs=("EVENT-INDEX.md",),
    tools=("vertical_search",),
    read_deny=("/DECISION-*", "/INTRADAY-DECISION-*", "/REVIEW-*", "/CANDIDATES.md"),
    prompt=PROMPT,
)
