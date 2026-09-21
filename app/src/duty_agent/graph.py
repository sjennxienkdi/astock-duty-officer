"""主图（plan §11）：deepagents 装配、白名单数据源工具、cassette 驱动的展示模型。

展示模式（plan §15.11）下模型是 `CassetteChatModel`：它按 fixture 里录好的回合依次吐出工具调用
与文本。图、权限、配额、EVIDENCE、引擎门禁全是真的，只有「判断内容」是录的——等价于 VCR 回放。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from deepagents.middleware.filesystem import FilesystemPermission
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool, tool

from duty_agent.agents import RoleRun, RoleSpec
from duty_agent.guardrails.source_adjudicator import Adjudicator, EvidenceLog, QuotaMeter
from duty_engine.storage import Archive


def output_glob(name: str) -> str:
    """把 `DECISION-gpt.md` / `DD/{code}/{date}.md` 变成档案根下的 glob。"""
    if "{" in name:
        return "/" + name.split("{", 1)[0] + "**"
    return "/" + name


def permissions_for(spec: RoleSpec) -> list[FilesystemPermission]:
    """编译角色权限（plan §4 / §15.7）。声明顺序即优先级，先匹配者生效。

    1. 允许读自己该写的档案；2. 按角色禁读他人结论；
    3. 内置写类工具（`write_file` / `edit_file` / `delete` 同属 write 操作）一律禁——
       档案只能通过 `submit_archive` 走只追加通道。
    """
    rules: list[FilesystemPermission] = []
    rules.append(
        FilesystemPermission(
            operations=["read"], paths=[output_glob(o) for o in spec.outputs], mode="allow"
        )
    )
    if spec.read_deny:
        rules.append(
            FilesystemPermission(operations=["read"], paths=list(spec.read_deny), mode="deny")
        )
    rules.append(FilesystemPermission(operations=["write"], paths=["/**"], mode="deny"))
    return rules


@dataclass
class RunContext:
    """一次角色运行的全部外部依赖。"""

    day: date
    fixtures: Path
    archive: Archive
    adjudicator: Adjudicator
    evidence: EvidenceLog
    clock: Callable[[], datetime]
    wrote: list[str] = field(default_factory=list)
    recall: Callable[[str, str, str], list[str]] | None = None

    @classmethod
    def build(
        cls,
        *,
        role: str,
        day: date,
        fixtures: Path,
        archive: Archive,
        quota: QuotaMeter,
        clock: Callable[[], datetime],
        recall: Callable[[str, str, str], list[str]] | None = None,
    ) -> RunContext:
        return cls(
            day=day,
            fixtures=fixtures,
            archive=archive,
            adjudicator=Adjudicator(today=day, quota=quota),
            evidence=EvidenceLog(role=role, archive=archive, day=day),
            clock=clock,
            recall=recall,
        )


def _read_fixture(root: Path, rel: str) -> Any:
    return json.loads((root / rel).read_text(encoding="utf-8"))


def make_tools(spec: RoleSpec, ctx: RunContext) -> list[BaseTool]:
    """按角色白名单生成工具。每次调用都过采信门槛并追加一行 EVIDENCE。"""
    tools: list[BaseTool] = []

    def logged(name: str, query: str, payload: Callable[[], Any]) -> str:
        stamp = ctx.clock()
        verdict, reason = ctx.adjudicator.judge(name, stamp=stamp)
        ctx.evidence.append(stamp, name, query, verdict, reason)
        if verdict == "rejected":
            return f"[{verdict}] {reason}"
        return json.dumps(payload(), ensure_ascii=False)

    if "quote_snapshot" in spec.tools:

        def quote_snapshot(code: str) -> str:
            """腾讯快照（fixture）：最新价、昨收、成交量。"""
            return logged(
                "quote_snapshot",
                code,
                lambda: _read_fixture(ctx.fixtures, f"quote/{ctx.day}.json").get(code, {}),
            )

        tools.append(tool(quote_snapshot))

    if "ifind_panel" in spec.tools:

        def ifind_panel(code: str) -> str:
            """iFinD 面板（fixture）：上市天数、日均成交额、是否 ST。"""
            return logged(
                "ifind_panel",
                code,
                lambda: _read_fixture(ctx.fixtures, "financial/ifind_panel.json").get(code, {}),
            )

        tools.append(tool(ifind_panel))

    if "vertical_search" in spec.tools:

        def vertical_search(query: str) -> str:
            """垂搜（fixture）：按标的或关键词返回带时间戳的资讯条目。"""
            return logged(
                "vertical_search",
                query,
                lambda: [
                    row
                    for row in _read_fixture(ctx.fixtures, "search/news.json")
                    if query in row["code"] or query in row["title"]
                ],
            )

        tools.append(tool(vertical_search))

    if "tianyancha_flags" in spec.tools:

        def tianyancha_flags(code: str) -> str:
            """工商与司法（fixture）：背调七条原始命中。"""
            return logged(
                "tianyancha_flags",
                code,
                lambda: _read_fixture(ctx.fixtures, "dd/tianyancha.json").get(code, {}),
            )

        tools.append(tool(tianyancha_flags))

    if "gm_kline" in spec.tools:

        def gm_kline(code: str) -> str:
            """掘金日 K（fixture）：近 5 日均量与涨跌幅序列。"""
            return logged(
                "gm_kline",
                code,
                lambda: _read_fixture(ctx.fixtures, "quote/kline_5d.json").get(code, {}),
            )

        tools.append(tool(gm_kline))

    if "recall" in spec.tools and ctx.recall is not None:
        recall_fn = ctx.recall

        def recall(query: str, doc_type: str = "", code: str = "") -> str:
            """研究记忆 KB 召回（plan §6）：filters 至少给一个。"""
            return logged(
                "recall",
                f"{query} doc_type={doc_type} code={code}",
                lambda: recall_fn(query, doc_type, code),
            )

        tools.append(tool(recall))

    def owns(file_path: str) -> bool:
        name = file_path.lstrip("/")
        for output in spec.outputs:
            prefix = output.split("{", 1)[0]
            if name == output or (prefix and name.startswith(prefix)):
                return True
        return False

    def submit_archive(file_path: str, content: str, append: bool = False) -> str:
        """交卷：只允许属于本角色的文件名，只追加不覆盖。"""
        name = file_path.lstrip("/")
        if not owns(name):
            return f"[rejected] {name} 不在 {spec.role} 的产出范围 {list(spec.outputs)} 内"
        if append:
            ctx.archive.append(ctx.day, name, content)
        else:
            ctx.archive.write_once(ctx.day, name, content)
        ctx.wrote.append(name)
        return f"[ok] {name}"

    tools.append(tool(submit_archive))
    return tools


class CassetteChatModel(GenericFakeChatModel):
    """按录制回合出牌的展示模型；工具绑定是空操作，调用由 cassette 直接给出。"""

    def bind_tools(
        self,
        tools: Sequence[Any],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> GenericFakeChatModel:
        return self


def load_cassette(path: Path) -> CassetteChatModel:
    """把 cassette JSON 展开成消息序列。

    形如 `{"turns": [{"content": "", "tool_calls": [{"name": ..., "args": {...}}]}]}`。
    """
    raw: Mapping[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    messages: list[AIMessage] = []
    for index, turn in enumerate(raw["turns"]):
        calls = [
            {
                "name": call["name"],
                "args": dict(call.get("args", {})),
                "id": f"{path.stem}-{index}-{inner}-{call['name']}",
            }
            for inner, call in enumerate(turn.get("tool_calls", []))
        ]
        messages.append(AIMessage(content=turn.get("content", ""), tool_calls=calls))
    if not messages or messages[-1].tool_calls:
        messages.append(AIMessage(content="交卷完成。"))
    return CassetteChatModel(messages=iter(messages))


def build_agent(
    spec: RoleSpec, ctx: RunContext, model: CassetteChatModel, *, root_dir: Path
) -> Any:
    """装配一个 deep agent：工具白名单 + 档案后端 + 只追加门禁。"""
    return create_deep_agent(
        model=model,
        tools=make_tools(spec, ctx),
        system_prompt=spec.prompt,
        backend=FilesystemBackend(root_dir=str(root_dir)),
        permissions=permissions_for(spec),
    )


def run_role(
    spec: RoleSpec,
    ctx: RunContext,
    cassette: Path,
    *,
    root_dir: Path,
    ask: str,
) -> RoleRun:
    """跑一个角色到交卷，返回它写了哪些档案、工具回了什么、是否降级。"""
    agent = build_agent(spec, ctx, load_cassette(cassette), root_dir=root_dir)
    state = agent.invoke({"messages": [{"role": "user", "content": ask}]})
    replies = [str(message.content) for message in state["messages"] if message.type == "tool"]
    evidence = "\n".join(ctx.evidence.lines())
    return RoleRun(
        role=spec.role,
        wrote=list(ctx.wrote),
        low_info="配额耗尽" in evidence,
        replies=replies,
    )
