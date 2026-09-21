"""召回入口（plan §6）：`filters` 至少含 doc_type 或 code，裸查询直接抛错。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from duty_agent.memory.store import KbStore, Recalled


@dataclass(frozen=True)
class Filters:
    """元数据过滤。两个都给则取交集。"""

    doc_type: str = ""
    code: str = ""

    @property
    def empty(self) -> bool:
        return not self.doc_type and not self.code


def recall(
    store: KbStore, query: str, filters: Filters, *, top_k: int = 5, today: str = ""
) -> list[Recalled]:
    """带门槛的召回。"""
    if filters.empty:
        raise ValueError("裸查询被禁止：filters 至少含 doc_type 或 code 之一")
    results = store.search(query, doc_type=filters.doc_type, code=filters.code, top_k=top_k)
    if today:
        results = [r for r in results if r.chunk.as_of <= today or not r.chunk.as_of]
    return results


def as_citations(results: list[Recalled]) -> list[str]:
    """召回块转成 `[doc@as_of] 正文` 文本，走 §5.3 采信门槛。"""
    return [f"{r.chunk.citation} {r.chunk.text}" for r in results]


def tool_bridge(store: KbStore, top_k: int = 5) -> Callable[[str, str, str], list[str]]:
    """给 `RunContext.recall` 用的适配器：`(query, doc_type, code) -> 文本列表`。"""

    def _recall(query: str, doc_type: str = "", code: str = "") -> list[str]:
        return as_citations(
            recall(store, query, Filters(doc_type=doc_type, code=code), top_k=top_k)
        )

    return _recall
