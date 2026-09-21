"""订单十态状态机（plan §2.3 / §7）：表驱动转移矩阵，非法转移抛错。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from enum import StrEnum

from duty_engine.clock import ensure_shanghai
from duty_engine.storage import Store, require_int


class OrderState(StrEnum):
    """十个状态名冻结（plan §2.3），值即代码标识符。"""

    DRAFT = "draft"
    APPROVED = "approved"
    QUEUED = "queued"
    SUBMITTED = "submitted"
    FILLED = "filled"
    PARTIAL = "partial"
    REJECTED = "rejected"
    CANCELED = "canceled"
    EXPIRED = "expired"
    ARCHIVED = "archived"


ALL_STATES: tuple[OrderState, ...] = tuple(OrderState)

# 转移矩阵取保守最小集：人工确认之前不存在任何通往 submitted 的路。
TRANSITIONS: dict[OrderState, frozenset[OrderState]] = {
    OrderState.DRAFT: frozenset({OrderState.APPROVED, OrderState.REJECTED}),
    OrderState.APPROVED: frozenset({OrderState.QUEUED, OrderState.REJECTED}),
    OrderState.QUEUED: frozenset({OrderState.SUBMITTED, OrderState.CANCELED, OrderState.EXPIRED}),
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

# 中文只出现在展示层（plan §2.3），此表是展示层唯一来源。
HUMAN_LABEL_ZH: dict[OrderState, str] = {
    OrderState.DRAFT: "草稿",
    OrderState.APPROVED: "风控通过，待人工确认",
    OrderState.QUEUED: "已确认，待提交",
    OrderState.SUBMITTED: "已提交",
    OrderState.FILLED: "全部成交",
    OrderState.PARTIAL: "部分成交",
    OrderState.REJECTED: "已否决",
    OrderState.CANCELED: "已撤销",
    OrderState.EXPIRED: "已过期",
    OrderState.ARCHIVED: "已归档",
}

SIDE_WORDS = frozenset({"buy", "sell"})


class IllegalTransition(RuntimeError):
    """非法状态转移。"""


@dataclass(frozen=True)
class Order:
    """一笔订单。金额与手数一律整数。"""

    order_id: str
    trade_date: date
    code: str
    name: str
    side: str
    state: OrderState
    qty_lots: int
    limit_cents: int
    amount_cents: int
    intent_id: str | None = None

    def __post_init__(self) -> None:
        if self.side not in SIDE_WORDS:
            raise ValueError(f"side 只允许 buy/sell，收到 {self.side!r}")
        require_int("qty_lots", self.qty_lots)
        require_int("limit_cents", self.limit_cents)
        require_int("amount_cents", self.amount_cents)


def is_terminal(state: OrderState) -> bool:
    """是否为无后继的终态。"""
    return not TRANSITIONS[state]


def can_transition(frm: OrderState, to: OrderState) -> bool:
    """查询转移是否合法。"""
    return to in TRANSITIONS[frm]


def transition(
    order: Order, to: OrderState, *, at: datetime, intent_id: str | None = None
) -> Order:
    """推进状态；非法即抛，通往 `queued` 必须带 intent_id。"""
    ensure_shanghai(at)
    if not can_transition(order.state, to):
        raise IllegalTransition(f"{order.state} -> {to} 非法")
    if to is OrderState.QUEUED and intent_id is None:
        raise IllegalTransition("进入 queued 必须携带 intent_id")
    return replace(order, state=to, intent_id=intent_id or order.intent_id)


def save(store: Store, order: Order, at: datetime) -> None:
    """订单落 `orders` 表。"""
    ensure_shanghai(at)
    store.insert_order(
        order.order_id,
        order.trade_date,
        order.code,
        order.name,
        order.side,
        str(order.state),
        order.qty_lots,
        order.limit_cents,
        order.amount_cents,
        order.intent_id,
        at,
    )
    store.upsert_order_state(order.order_id, str(order.state), at)
