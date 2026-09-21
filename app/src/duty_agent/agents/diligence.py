"""背调 Agent（plan §4.4）：新码触发，七条检查，无否决权。"""

from __future__ import annotations

from duty_agent.agents import RoleSpec, prompt_for

PROMPT = prompt_for(
    "diligence",
    """职责：screener 产出新码即激活。夜间 ≤2 只深度；T 晨 08:00–08:44 补背调 ≤2 只；
近 10 交易日已有 DD 档的直接复用，不消耗配额。覆盖不到的新码在 CANDIDATES.md 标 `无背调`。
检查项固定七条，一条不能少：质押 / 失信 / 诉讼 / 开庭 / 终本 / 解禁 / 对外担保。
权限：你【没有否决权】。发现硬雷只写报告并打 hard_red=true，
是否移池由引擎在次日池锁定按规则浅筛执行。""",
)

SPEC = RoleSpec(
    role="diligence",
    describe="新码背调七条，供参考，无否决权",
    outputs=("DD/{code}/{date}.md",),
    tools=("tianyancha_flags", "quote_snapshot"),
    read_deny=("/DECISION-*", "/INTRADAY-DECISION-*", "/REVIEW-*", "/CROSS_EXAM.md"),
    prompt=PROMPT,
)
