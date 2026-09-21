"""存储（plan §7）：SQLite 三表 + 只追加的文件档案。引擎是唯一写库者。"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from duty_engine.clock import ensure_shanghai

# plan §4.1 / §5.1 / §5.4 / §5.5 的告警类别 + 池外标的越权一类
ALERT_KINDS = frozenset({"absent", "volatility", "sig001", "hard_red", "cooldown", "offpool"})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    order_id     TEXT PRIMARY KEY,
    trade_date   TEXT NOT NULL,
    code         TEXT NOT NULL,
    name         TEXT NOT NULL,
    side         TEXT NOT NULL,
    state        TEXT NOT NULL,
    qty_lots     INTEGER NOT NULL,
    limit_cents  INTEGER NOT NULL,
    amount_cents INTEGER NOT NULL,
    intent_id    TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ledger (
    entry_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date   TEXT NOT NULL,
    code         TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    note         TEXT NOT NULL,
    created_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alerts (
    alert_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    at        TEXT NOT NULL,
    kind      TEXT NOT NULL,
    subject   TEXT NOT NULL,
    detail    TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class Alert:
    """一条告警档案记录。"""

    at: datetime
    kind: str
    subject: str
    detail: str

    def __post_init__(self) -> None:
        if self.kind not in ALERT_KINDS:
            raise ValueError(f"未知告警类别: {self.kind}")
        ensure_shanghai(self.at)


class Store:
    """三表 SQLite 存储，惰性建库。"""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self._db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def insert_alert(self, alert: Alert) -> None:
        self.conn.execute(
            "INSERT INTO alerts (at, kind, subject, detail) VALUES (?, ?, ?, ?)",
            (alert.at.isoformat(), alert.kind, alert.subject, alert.detail),
        )
        self.conn.commit()

    def alerts(self, kind: str | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM alerts" + (" WHERE kind = ?" if kind else "") + " ORDER BY alert_id"
        with closing(self.conn.execute(sql, (kind,) if kind else ())) as cursor:
            return list(cursor.fetchall())

    def insert_ledger(
        self, trade_date: date, code: str, amount_cents: int, note: str, at: datetime
    ) -> None:
        require_int("amount_cents", amount_cents)
        sql = (
            "INSERT INTO ledger (trade_date, code, amount_cents, note, created_at)"
            " VALUES (?, ?, ?, ?, ?)"
        )
        self.conn.execute(sql, (trade_date.isoformat(), code, amount_cents, note, at.isoformat()))
        self.conn.commit()

    def insert_order(
        self,
        order_id: str,
        trade_date: date,
        code: str,
        name: str,
        side: str,
        state: str,
        qty_lots: int,
        limit_cents: int,
        amount_cents: int,
        intent_id: str | None,
        at: datetime,
    ) -> None:
        require_int("qty_lots", qty_lots)
        require_int("limit_cents", limit_cents)
        require_int("amount_cents", amount_cents)
        stamp = at.isoformat()
        self.conn.execute(
            "INSERT OR REPLACE INTO orders (order_id, trade_date, code, name, side, state,"
            " qty_lots, limit_cents, amount_cents, intent_id, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                order_id,
                trade_date.isoformat(),
                code,
                name,
                side,
                state,
                qty_lots,
                limit_cents,
                amount_cents,
                intent_id,
                stamp,
                stamp,
            ),
        )
        self.conn.commit()

    def upsert_order_state(self, order_id: str, state: str, at: datetime) -> None:
        self.conn.execute(
            "UPDATE orders SET state = ?, updated_at = ? WHERE order_id = ?",
            (state, at.isoformat(), order_id),
        )
        self.conn.commit()

    def orders(self, state: str | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM orders" + (" WHERE state = ?" if state else "") + " ORDER BY order_id"
        with closing(self.conn.execute(sql, (state,) if state else ())) as cursor:
            return list(cursor.fetchall())


class Archive:
    """`results/daily/{YYYY-MM-DD}/` 档案，只追加不覆盖（plan §15.7）。"""

    def __init__(self, results_dir: Path) -> None:
        self._results_dir = results_dir

    def daily_dir(self, day: date) -> Path:
        path = self._results_dir / "daily" / day.isoformat()
        path.mkdir(parents=True, exist_ok=True)
        return path

    def path(self, day: date, name: str) -> Path:
        return self.daily_dir(day) / name

    def append(self, day: date, name: str, line: str) -> Path:
        target = self.path(day, name)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(line.rstrip("\n") + "\n")
        return target

    def write_once(self, day: date, name: str, text: str) -> Path:
        target = self.path(day, name)
        if target.exists():
            raise FileExistsError(f"档案只追加，禁止覆盖: {target}")
        target.write_text(text.rstrip("\n") + "\n", encoding="utf-8")
        return target

    def read(self, day: date, name: str) -> str:
        return self.path(day, name).read_text(encoding="utf-8")

    def exists(self, day: date, name: str) -> bool:
        return self.path(day, name).is_file()

    def mark_rejected(self, day: date, name: str) -> Path:
        """作废 = 改名加 `.REJECTED` 后缀，原文件不删。"""
        source = self.path(day, name)
        target = source.with_name(source.name + ".REJECTED")
        source.rename(target)
        return target


class AlertLog:
    """告警双写：SQLite `alerts` 表 + `ALERT.md` 追加一行。"""

    def __init__(self, store: Store, archive: Archive) -> None:
        self._store = store
        self._archive = archive

    def emit(self, alert: Alert) -> None:
        self._store.insert_alert(alert)
        day = ensure_shanghai(alert.at).date()
        line = f"{alert.at.isoformat()} kind={alert.kind} {alert.subject} {alert.detail}".rstrip()
        self._archive.append(day, "ALERT.md", line)


def require_int(field: str, value: int) -> int:
    """金额与仓位一律整数（plan §15.9）：拒绝 float 与 bool。"""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} 必须是整数，收到 {type(value).__name__}: {value!r}")
    return value
