"""全天回放（plan §8）：按时间展开全部档案 + 每角色取证链。"""

from __future__ import annotations

import streamlit as st

from app import archive_files, evidence_files, pick_day, read

day = pick_day()
if day is None:
    st.stop()

st.title(f"全天回放 · {day}")
st.caption("档案只追加、不覆盖；作废件以 `.REJECTED` 结尾原样保留，所以坏判断也能被复盘。")

st.subheader("档案时间线")
for name in archive_files(day):
    rejected = name.endswith(".REJECTED")
    with st.expander(f"{'⚠️ ' if rejected else ''}{name}"):
        if rejected:
            st.warning("本件已作废，保留原文用于复盘，未被删除。")
        st.markdown(read(day, name))

st.subheader("每角色取证链")
if evidence_files(day):
    for name in evidence_files(day):
        lines = [line for line in read(day, name).splitlines() if line.strip()]
        with st.expander(f"{name.rsplit('.', 1)[0]}（{len(lines)} 次调用）"):
            for line in lines:
                if "→ rejected" in line:
                    st.error(line)
                else:
                    st.write(line)
else:
    st.info("这一天没有取证记录。")
