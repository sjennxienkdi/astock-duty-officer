"""研究记忆页（plan §8）：检索框 + metadata filter + 召回块带 `[doc@as_of]`。"""

from __future__ import annotations

import streamlit as st

from app import kb_store, settings
from duty_agent.memory.recall_tool import Filters, recall

DOC_TYPES = ("experiment", "summary", "cross_exam", "events", "diligence")

st.title("研究记忆 KB")
st.caption(
    "KB 只收跨日有效的结论档：当天的 DECISION / CANDIDATES / PACK / EVENT-INDEX 一律不收，"
    "也不用于检索行情与新闻——那类事实必须单源、可审计。"
)

store = kb_store(str(settings().kb_index_path))
chunks = store.chunks()
counts = st.columns(len(DOC_TYPES))
for column, doc_type in zip(counts, DOC_TYPES, strict=True):
    column.metric(doc_type, sum(1 for c in chunks if c.doc_type == doc_type))

query = st.text_input("检索问题", key="kb-query", placeholder="缩量过滤为什么保留")
with st.container(horizontal=True):
    doc_type = st.selectbox("doc_type", ("",) + DOC_TYPES, key="kb-doc-type")
    code = st.text_input("code（如 300750）", key="kb-code")

if not query:
    st.info("输入问题后召回 top5。裸查询（不给 doc_type 也不给 code）会被直接拒绝。")
    st.stop()

try:
    results = recall(store, query, Filters(doc_type=doc_type, code=code), top_k=5)
except ValueError as exc:
    st.error(f"{exc}")
    st.stop()

if not results:
    st.warning("过滤条件下没有任何知识块。")
    st.stop()

for position, hit in enumerate(results, start=1):
    with st.expander(f"{position}. {hit.chunk.citation} · {hit.chunk.source_tier}"):
        st.markdown(hit.chunk.text)
        st.caption(f"RRF 得分 {hit.score:.4f} · code={hit.chunk.code or '—'}")
