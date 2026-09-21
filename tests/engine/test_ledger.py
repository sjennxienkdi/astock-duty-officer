"""账本整数分断言（plan §13）。"""

from __future__ import annotations

from datetime import date

import pytest

from duty_engine.ledger import Fill, Ledger, Position, cents, lot_amount_cents

DAY = date(2026, 9, 16)


def test_ledger_cents_only() -> None:
    with pytest.raises(TypeError):
        cents(1.5)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        lot_amount_cents(1, 12.5)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        Ledger.open(100_000.0)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        Position("600519", "贵州茅台", 1, 13500000.5)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        Fill(DAY, "000001", "平安银行", "buy", 83, 1200, 9_960_000.0)  # type: ignore[arg-type]


def test_ledger_amount_matches_lots_and_price() -> None:
    with pytest.raises(ValueError):
        Fill(DAY, "000001", "平安银行", "buy", 83, 1200, 9_960_001)


def test_ledger_fill_moves_cash_and_position() -> None:
    ledger = Ledger.open(100_000_000)
    fill = Fill(DAY, "000001", "平安银行", "buy", 83, 1200, 83 * 100 * 1200)
    after = ledger.apply_fill(fill)
    assert after.cash_cents == 100_000_000 - 9_960_000
    assert after.positions["000001"].qty_lots == 83
    assert ledger.cash_cents == 100_000_000  # 旧账本未被改写
    prices = {"000001": 1200}
    assert after.exposure_bps(prices) == 9_960_000 * 10_000 // 100_000_000
    assert isinstance(after.exposure_bps(prices), int)


def test_ledger_sell_cannot_exceed_holding() -> None:
    ledger = Ledger.open(0, [Position("000001", "平安银行", 2, 240_000)])
    with pytest.raises(ValueError):
        ledger.apply_fill(Fill(DAY, "000001", "平安银行", "sell", 3, 1200, 360_000))


def test_ledger_sell_releases_pro_rata_cost() -> None:
    ledger = Ledger.open(0, [Position("000001", "平安银行", 4, 480_000)])
    after = ledger.apply_fill(Fill(DAY, "000001", "平安银行", "sell", 1, 1200, 120_000))
    assert after.positions["000001"].qty_lots == 3
    assert after.positions["000001"].cost_cents == 360_000
    assert after.cash_cents == 120_000
