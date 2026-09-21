"""选股 Agent（plan §4.2）：T-1 深研究 + T 晨修正。"""

from __future__ import annotations

from duty_agent.agents import RoleSpec, prompt_for

PROMPT = prompt_for(
    "screener",
    """职责：T-1 23:30 深研究出 POOL-DRAFT.md 与新码清单；T 07:55–08:20 修正出 CANDIDATES.md。
硬规则：持仓股必须强制入池，任何理由都不许剔除——包括它看起来该被剔。
新码清单 = 池内且近 10 交易日无 DD 档的标的。
配额：iFinD ≤8 / 垂搜 ≤12 / 掘金 ≤6。耗尽即打 LOW_INFO 出池。
不读任何 DECISION-*.md：那是你下游的产物，读了就是倒果为因。""",
)

SPEC = RoleSpec(
    role="screener",
    describe="T-1 深研究 + T 晨修正，持仓股强制入池",
    outputs=("POOL-DRAFT.md", "CANDIDATES.md"),
    tools=("quote_snapshot", "ifind_panel", "vertical_search", "gm_kline"),
    read_deny=("/DECISION-*", "/INTRADAY-DECISION-*", "/REVIEW-*", "/CROSS_EXAM.md"),
    prompt=PROMPT,
)
