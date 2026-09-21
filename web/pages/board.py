"""值班台首页（plan §8）：节奏表进度、池与锁定状态、订单十态看板。"""

from __future__ import annotations

import streamlit as st

from app import alert_rows, known_days, morning_rows, order_rows, pick_day, read, schedule_state
from duty_engine.orders import ALL_STATES, HUMAN_LABEL_ZH

LABEL_BY_VALUE = {state.value: HUMAN_LABEL_ZH[state] for state in ALL_STATES}

day = pick_day()
if day is None:
    st.stop()

st.title(f"值班台 · {day}")
st.caption("本页所有数字来自引擎；agent 的文字一律标「评论」。本页只读。")

pool_row = read(day, "MORNING.md").splitlines()
version = next(
    (line.split(": ", 1)[1] for line in pool_row if line.startswith("pool_version")), "未锁定"
)
total = next(
    (int(line.split(": ", 1)[1]) for line in pool_row if line.startswith("portfolio_cents")), 0
)

left, middle, right = st.columns(3)
left.metric("池版本（引擎）", version)
middle.metric("账户总值·分（引擎）", f"{total:,}")
right.metric("当日告警", len(alert_rows(day)))

st.subheader("一天节奏")
st.dataframe(schedule_state(day), hide_index=True, width="stretch")

st.subheader("池与计划锁定")
rows = morning_rows(day)
if rows:
    st.dataframe(
        [
            {
                "标的": f"{row.get('code')} {row.get('name')}",
                "stance": row.get("stance", "—"),
                "目标 bps（引擎）": row.get("target_bps", "—"),
                "现仓 bps（引擎）": row.get("current_bps", "—"),
                "冻结触发线·分（引擎）": row.get("protect_trigger_cents", "—"),
                "票数": row.get("votes", "—"),
                "冲突": row.get("conflict", "—"),
            }
            for row in rows
        ],
        hide_index=True,
        width="stretch",
    )
else:
    st.info("还没有 08:45 锁定的计划。")

st.subheader("订单十态看板")
orders = order_rows(day)
if orders:
    counts = {
        state.value: sum(1 for o in orders if o["state"] == state.value) for state in ALL_STATES
    }
    cols = st.columns(len(ALL_STATES))
    for column, state in zip(cols, ALL_STATES, strict=True):
        column.metric(str(state), counts[state.value], help=HUMAN_LABEL_ZH[state])
    st.dataframe(
        [
            {
                "订单": o["order_id"],
                "标的": f"{o['code']} {o['name']}",
                "方向": o["side"],
                "状态": LABEL_BY_VALUE[o["state"]],
                "手数（引擎）": o["qty_lots"],
                "金额·分（引擎）": f"{int(o['amount_cents']):,}",
                "intent_id": o["intent_id"] or "—",
            }
            for o in orders
        ],
        hide_index=True,
        width="stretch",
    )
else:
    st.info("今天没有任何订单。零候选日与零换仓日都是正常结果。")

st.caption(f"可选日期：{', '.join(known_days())}")
