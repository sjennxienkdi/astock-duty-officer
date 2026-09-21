"""评测页（plan §8）：测试数、覆盖率、recall@5/MRR、已关闭实验轴清单。"""

from __future__ import annotations

import streamlit as st

from app import frontmatter, read_root, settings

st.title("评测")
st.caption("本页只展示 `EVALUATION.md` 里由命令产出的数字，不在页面里重算。")

lines = [line for line in read_root("EVALUATION.md").splitlines() if line.startswith("|")]
if lines:
    header = [cell.strip() for cell in lines[0].strip("|").split("|")]
    rows = [[cell.strip() for cell in line.strip("|").split("|")] for line in lines[2:]]
    st.dataframe(
        [dict(zip(header, row, strict=False)) for row in rows], hide_index=True, width="stretch"
    )
else:
    st.error("还没跑过 `uv run python -m duty_agent.memory.eval --write`。")

st.subheader("实验轴台账")
st.caption(
    "来自 quant-lab 结题卡。关闭的轴不再复现，保留的轴落成配置——缩量过滤就是池锁定的成交额门槛。"
)

cards = sorted((settings().examples_dir / "fixtures" / "quant-lab").glob("*.md"))
for card in cards:
    text = card.read_text(encoding="utf-8")
    meta = frontmatter(text)
    closed = "关闭" in meta.get("title", "") or "关闭" in text[:400]
    badge = ":red[已关闭]" if closed else ":green[保留]"
    with st.expander(f"{badge} {meta.get('title', card.stem)}"):
        st.markdown(text.split("---", 2)[-1].strip())
        st.caption(
            f"doc_id={meta.get('doc_id')} · as_of={meta.get('as_of')}"
            f" · tier={meta.get('source_tier')}"
        )
