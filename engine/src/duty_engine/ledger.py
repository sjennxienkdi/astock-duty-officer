"""账本（plan §7 / §15.9）：金额一律整数分、仓位一律整数 bps，float 进不来。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import NewType

from duty_engine.clock import ensure_shanghai
from duty_engine.storage import Store, require_int

Bps = NewType("Bps", int)
Cents = NewType("Cents", int)

SHARES_PER_LOT = 100


def cents(value: int) -> Cents:
    """构造金额（分），非整数直接抛错。"""
    return Cents(require_int("amount_cents", value))


def bps(value: int) -> Bps:
    """构造仓位（基点）。"""
    return Bps(require_int("position_bps", value))


def lot_amount_cents(qty_lots: int, price_cents: int) -> Cents:
    """手数 × 每手股数 × 每股分价，全程整数。"""
    shares = require_int("qty_lots", qty_lots) * SHARES_PER_LOT
    return cents(shares * require_int("price_cents", price_cents))


@dataclass(frozen=True)
class Position:
    """一只标的的持仓：手数与总成本，均为整数。"""

    code: str
    name: str
    qty_lots: int
    cost_cents: int

    def __post_init__(self) -> None:
        require_int("qty_lots", self.qty_lots)
        require_int("cost_cents", self.cost_cents)


@dataclass(frozen=True)
class Fill:
    """一笔成交回填。"""

    trade_date: date
    code: str
    name: str
    side: str
    qty_lots: int
    price_cents: int
    amount_cents: int

    def __post_init__(self) -> None:
        require_int("qty_lots", self.qty_lots)
        require_int("price_cents", self.price_cents)
        require_int("amount_cents", self.amount_cents)
        if self.side not in ("buy", "sell"):
            raise ValueError(f"side 只允许 buy/sell，收到 {self.side!r}")
        if self.qty_lots < 1:
            raise ValueError(f"成交手数必须为正，收到 {self.qty_lots}")
        expected = lot_amount_cents(self.qty_lots, self.price_cents)
        if self.amount_cents != expected:
            raise ValueError(f"金额与手数理不清: amount_cents={self.amount_cents} 应为 {expected}")


@dataclass(frozen=True)
class Ledger:
    """现金 + 持仓账本；`apply` 返回新账本，旧账本不被改写。"""

    cash_cents: int
    positions: Mapping[str, Position]
    fills: tuple[Fill, ...] = ()

    @classmethod
    def open(cls, cash_cents: int, holdings: Iterable[Position] = ()) -> Ledger:
        """以给定现金和持仓开账。"""
        return cls(cash_cents=cents(cash_cents), positions={p.code: p for p in holdings})

    def apply_fill(self, fill: Fill) -> Ledger:
        """回填成交：买入花现金、卖出收现金，成本同步。"""
        positions = dict(self.positions)
        current = positions.get(fill.code) or Position(fill.code, fill.name, 0, cents(0))
        if fill.side == "buy":
            cash = cents(self.cash_cents - fill.amount_cents)
            updated = replace(
                current,
                name=fill.name,
                qty_lots=current.qty_lots + fill.qty_lots,
                cost_cents=cents(current.cost_cents + fill.amount_cents),
            )
        else:
            if fill.qty_lots > current.qty_lots:
                raise ValueError(f"卖出超过持仓: {fill.code} {fill.qty_lots} > {current.qty_lots}")
            cash = cents(self.cash_cents + fill.amount_cents)
            released = cents(current.cost_cents * fill.qty_lots // current.qty_lots)
            updated = replace(
                current,
                name=fill.name,
                qty_lots=current.qty_lots - fill.qty_lots,
                cost_cents=cents(current.cost_cents - released),
            )
        positions[fill.code] = updated
        return Ledger(cash_cents=cash, positions=positions, fills=self.fills + (fill,))

    def cost_basis_cents(self) -> Cents:
        """全部持仓成本合计。"""
        return cents(sum((p.cost_cents for p in self.positions.values()), start=0))

    def market_value_cents(self, price_cents: Mapping[str, int]) -> Cents:
        """按给定每股分价算市值；缺价直接抛错，不静默估。"""
        total = 0
        for code, position in self.positions.items():
            if position.qty_lots == 0:
                continue
            price = require_int("price_cents", price_cents[code])
            total += lot_amount_cents(position.qty_lots, price)
        return cents(total)

    def unrealized_pnl_cents(self, price_cents: Mapping[str, int]) -> Cents:
        """浮盈（分）= 市值 - 成本。"""
        return cents(self.market_value_cents(price_cents) - self.cost_basis_cents())

    def total_cents(self, price_cents: Mapping[str, int]) -> Cents:
        """账户总值 = 现金 + 市值。"""
        return cents(self.cash_cents + self.market_value_cents(price_cents))

    def exposure_bps(self, price_cents: Mapping[str, int]) -> Bps:
        """仓位占比 = 市值 / 总值 × 10000，整数向下取整。"""
        total = self.total_cents(price_cents)
        if total <= 0:
            raise ValueError("总值非正，无法计算仓位")
        return bps(self.market_value_cents(price_cents) * 10000 // total)

    def persist(self, store: Store, at: datetime) -> None:
        """成交逐笔落 `ledger` 表（plan §7 三表之一）。"""
        ensure_shanghai(at)
        for fill in self.fills:
            store.insert_ledger(
                fill.trade_date,
                fill.code,
                fill.amount_cents,
                f"{fill.side} {fill.name} {fill.qty_lots}手 @{fill.price_cents}",
                at,
            )
