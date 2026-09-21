"""订单十态全转移矩阵断言（plan §13）。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from conftest import at
from duty_engine.orders import (
    ALL_STATES,
    TRANSITIONS,
    IllegalTransition,
    Order,
    OrderState,
    can_transition,
    is_terminal,
    save,
    transition,
)
from duty_engine.storage import Store

DAY = date(2026, 9, 16)


def make_order(state: OrderState) -> Order:
    return Order(
        order_id=f"t-{state}",
        trade_date=DAY,
        code="000001",
        name="平安银行",
        side="buy",
        state=state,
        qty_lots=1,
        limit_cents=1200,
        amount_cents=120_000,
    )


def test_orders_full_transition_matrix() -> None:
    """10×10 全覆盖：合法集与表一致，非法集一律抛错。"""
    expected: dict[OrderState, frozenset[OrderState]] = {
        OrderState.DRAFT: frozenset({OrderState.APPROVED, OrderState.REJECTED}),
        OrderState.APPROVED: frozenset({OrderState.QUEUED, OrderState.REJECTED}),
        OrderState.QUEUED: frozenset(
            {OrderState.SUBMITTED, OrderState.CANCELED, OrderState.EXPIRED}
        ),
        OrderState.SUBMITTED: frozenset(
            {OrderState.FILLED, OrderState.PARTIAL, OrderState.CANCELED, OrderState.EXPIRED}
        ),
        OrderState.PARTIAL: frozenset({OrderState.FILLED, OrderState.CANCELED}),
        OrderState.FILLED: frozenset({OrderState.ARCHIVED}),
        OrderState.REJECTED: frozenset({OrderState.ARCHIVED}),
        OrderState.CANCELED: frozenset({OrderState.ARCHIVED}),
        OrderState.EXPIRED: frozenset({OrderState.ARCHIVED}),
        OrderState.ARCHIVED: frozenset(),
    }
    assert TRANSITIONS == expected
    assert len(ALL_STATES) == 10
    for frm in ALL_STATES:
        for to in ALL_STATES:
            legal = to in expected[frm]
            assert can_transition(frm, to) is legal
            order = make_order(frm)
            if legal and to is not OrderState.QUEUED:
                assert transition(order, to, at=at("09:00")).state is to
            elif legal:
                with pytest.raises(IllegalTransition):
                    transition(order, to, at=at("09:00"))
                assert transition(order, to, at=at("09:00"), intent_id="i-1").state is to
            else:
                with pytest.raises(IllegalTransition):
                    transition(order, to, at=at("09:00"), intent_id="i-1")


def test_orders_illegal_transition_raises() -> None:
    draft = make_order(OrderState.DRAFT)
    with pytest.raises(IllegalTransition):
        transition(draft, OrderState.SUBMITTED, at=at("09:00"), intent_id="i-1")
    with pytest.raises(IllegalTransition):
        transition(make_order(OrderState.FILLED), OrderState.DRAFT, at=at("15:00"))
    with pytest.raises(IllegalTransition):
        transition(make_order(OrderState.APPROVED), OrderState.QUEUED, at=at("09:00"))


def test_orders_terminal_states_have_no_successor() -> None:
    terminal = {s for s in ALL_STATES if is_terminal(s)}
    assert terminal == {OrderState.ARCHIVED}


def test_orders_save_persists_state(tmp_path: Path) -> None:
    store = Store(tmp_path / "duty.sqlite3")
    order = transition(make_order(OrderState.DRAFT), OrderState.APPROVED, at=at("08:45"))
    save(store, order, at("08:45"))
    rows = store.orders()
    assert len(rows) == 1
    assert rows[0]["state"] == "approved"
    assert rows[0]["amount_cents"] == 120_000
