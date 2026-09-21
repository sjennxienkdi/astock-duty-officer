"""人工确认页（plan §8 / §5.6）：唯一放行口，引擎数字与 agent 评论分栏。"""

from __future__ import annotations

from datetime import date

import streamlit as st

from app import morning_rows, order_rows, pick_day, planner
from duty_agent.guardrails.intent_guard import TurnLedger, UnverifiedIntent
from duty_engine.orders import Order, OrderState


def trigger_of(rows: list[dict[str, object]], code: str) -> object:
    """该标的的冻结触发线（引擎数字）。"""
    row = next((r for r in rows if r.get("code") == code), {})
    return row.get("protect_trigger_cents", "—")


day = pick_day()
if day is None:
    st.stop()

pl = planner(day)
picked = date.fromisoformat(day)
rows = morning_rows(day)
st.title(f"人工确认 · {day}")
st.caption("本页是系统里唯一能推进订单状态的地方。微信卡片只给链接，不给按钮。")

approved = [row for row in order_rows(day) if row["state"] == OrderState.APPROVED.value]
if not approved:
    st.info("没有处于「风控通过，待人工确认」的订单。")
    st.stop()

for row in approved:
    order = Order(
        order_id=str(row["order_id"]),
        trade_date=pl.now.date(),
        code=str(row["code"]),
        name=str(row["name"]),
        side=str(row["side"]),
        state=OrderState.APPROVED,
        qty_lots=int(row["qty_lots"]),
        limit_cents=int(row["limit_cents"]),
        amount_cents=int(row["amount_cents"]),
        intent_id=None,
    )
    st.subheader(f"{order.code} {order.name} · {order.side}")
    engine_col, comment_col = st.columns(2, gap="large")
    with engine_col:
        st.markdown("**引擎数字（唯一真相源）**")
        st.dataframe(
            [
                {"字段": "手数", "值": order.qty_lots},
                {"字段": "限价·分", "值": order.limit_cents},
                {"字段": "金额·分", "值": order.amount_cents},
                {"字段": "冻结触发线·分", "值": trigger_of(rows, order.code)},
            ],
            hide_index=True,
            width="stretch",
        )
    with comment_col:
        st.markdown("**评论（agent 判断，不构成指令）**")
        for text in pl.stance_summaries(picked, order.code) or [
            f"{order.code} 当日无 stance 理由记录"
        ]:
            st.write(text)

    with st.form(key=f"confirm-{order.order_id}"):
        intent_id = st.text_input(
            "intent_id（留空则用下方说明新建一条真实用户轮次）", key=f"intent-{order.order_id}"
        )
        note = st.text_input("本轮说明", key=f"note-{order.order_id}")
        submitted = st.form_submit_button("确认并提交")

    if not submitted:
        continue
    ledger = TurnLedger(pl.settings.turn_ledger_path())
    try:
        used = (
            intent_id
            or ledger.record(note or f"确认 {order.code}", origin="user", at=pl.now).intent_id
        )
        moved = pl.confirm(order, used)
    except UnverifiedIntent as exc:
        st.error(f"拒绝放行：{exc}")
    else:
        st.success(f"{order.order_id} → {moved.state}（{moved.intent_id}）")
