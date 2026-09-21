"""存储与档案（plan §7 / §15.7）断言。"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import AT_POOL_LOCK
from duty_engine.clock import shanghai
from duty_engine.storage import Alert, AlertLog, Archive, Store


def test_storage_creates_three_tables(tmp_path: Path) -> None:
    store = Store(tmp_path / "duty.sqlite3")
    names = {
        row["name"]
        for row in store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"orders", "ledger", "alerts"} <= names


def test_alert_writes_both_db_and_archive(alert_env: tuple[Store, Archive, AlertLog]) -> None:
    store, archive, log = alert_env
    log.emit(Alert(AT_POOL_LOCK, "absent", "glm", "08:44 前未交卷"))
    assert store.alerts("absent")[0]["subject"] == "glm"
    assert archive.read(AT_POOL_LOCK.date(), "ALERT.md").strip().endswith("08:44 前未交卷")


def test_alert_rejects_unknown_kind(alert_env: tuple[Store, Archive, AlertLog]) -> None:
    with pytest.raises(ValueError):
        Alert(AT_POOL_LOCK, "催单", "600519", "不该存在")


def test_alert_log_appends_not_overwrites(alert_env: tuple[Store, Archive, AlertLog]) -> None:
    _, archive, log = alert_env
    log.emit(Alert(AT_POOL_LOCK, "absent", "glm", "第一条"))
    log.emit(Alert(shanghai(2026, 9, 16, "09:35:00"), "volatility", "000001", "第二条"))
    lines = archive.read(AT_POOL_LOCK.date(), "ALERT.md").splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("2026-09-16T08:20:00+08:00")


def test_archive_refuses_to_overwrite(tmp_path: Path) -> None:
    archive = Archive(tmp_path)
    archive.write_once(AT_POOL_LOCK.date(), "MORNING.md", "# 一版")
    with pytest.raises(FileExistsError):
        archive.write_once(AT_POOL_LOCK.date(), "MORNING.md", "# 二版")
    assert archive.read(AT_POOL_LOCK.date(), "MORNING.md") == "# 一版\n"


def test_archive_reject_renames_keeps_history(tmp_path: Path) -> None:
    archive = Archive(tmp_path)
    day = AT_POOL_LOCK.date()
    archive.write_once(day, "DECISION-gpt.md", "原文")
    target = archive.mark_rejected(day, "DECISION-gpt.md")
    assert target.name == "DECISION-gpt.md.REJECTED"
    assert target.read_text(encoding="utf-8") == "原文\n"
    assert not archive.exists(day, "DECISION-gpt.md")


def test_storage_ledger_row_roundtrip(tmp_path: Path) -> None:
    store = Store(tmp_path / "duty.sqlite3")
    store.insert_ledger(AT_POOL_LOCK.date(), "000001", 9_960_000, "buy 83手", AT_POOL_LOCK)
    row = store.conn.execute("SELECT * FROM ledger").fetchone()
    assert row["amount_cents"] == 9_960_000
    with pytest.raises(TypeError):
        store.insert_ledger(AT_POOL_LOCK.date(), "000001", 99.5, "float", AT_POOL_LOCK)  # type: ignore[arg-type]
