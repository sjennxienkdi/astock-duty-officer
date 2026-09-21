"""配置（plan §7 / §10）：配额、阈值、路径全部集中在这里，不散落在代码里。"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from duty_engine.freeze import EdgeGate, Sizing
from duty_engine.monitor import MonitorConfig


@dataclass(frozen=True)
class Quota:
    """取证配额（plan §4.2）：每次会话。耗尽只能打 LOW_INFO。"""

    ifind: int = 8
    vertical_search: int = 12
    gm_kline: int = 6


@dataclass(frozen=True)
class IntradayLimits:
    """盘中冷却（plan §4.5）：超限只写 ALERT。"""

    per_code: int = 2
    global_max: int = 4


class Settings(BaseSettings):
    """运行配置。展示模式是本仓库唯一支持的模式（plan §15.11）。"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    display_mode: bool = True
    results_dir: Path = Path("results")
    examples_dir: Path = Path("examples/replay-2026-09-16")
    db_path: Path = Path("results/duty.sqlite3")
    outbox_dir: Path = Path("outbox")
    confirm_base_url: str = "http://127.0.0.1:8501/confirm"
    wecom_webhook_url: str = ""
    portfolio_cents: int = 100_000_000
    llm_model: str = ""
    quota_ifind: int = 8
    quota_vertical_search: int = 12
    quota_gm_kline: int = 6
    intraday_per_code: int = 2
    intraday_global_max: int = 4
    edge_gate_min_listed_days: int = 250
    edge_gate_min_avg_amount_cents: int = 8_000_000_000
    intraday_move_trigger_bps: int = 300
    intraday_volume_multiple_bps: int = 25_000
    slow_interval_seconds: int = 300
    fast_interval_seconds: int = 60
    stop_loss_bps: int = 300
    single_name_max_bps: int = 1_000
    kb_index_path: Path = Path("results/kb.sqlite3")
    kb_recall_top_k: int = 5
    decision_tags: str = "gpt,claude,glm"

    @property
    def quota(self) -> Quota:
        return Quota(self.quota_ifind, self.quota_vertical_search, self.quota_gm_kline)

    @property
    def intraday(self) -> IntradayLimits:
        return IntradayLimits(self.intraday_per_code, self.intraday_global_max)

    @property
    def edge_gate(self) -> EdgeGate:
        """池锁定门槛（plan §5.1）。"""
        return EdgeGate(
            min_listed_days=self.edge_gate_min_listed_days,
            min_avg_amount_cents=self.edge_gate_min_avg_amount_cents,
        )

    @property
    def sizing(self) -> Sizing:
        """算仓参数（plan §5.1）。"""
        return Sizing(
            single_name_max_bps=self.single_name_max_bps, stop_loss_bps=self.stop_loss_bps
        )

    @property
    def monitor(self) -> MonitorConfig:
        """三判定与调频参数（plan §5.5）。"""
        return MonitorConfig(
            move_trigger_bps=self.intraday_move_trigger_bps,
            volume_multiple_bps=self.intraday_volume_multiple_bps,
            slow_interval_seconds=self.slow_interval_seconds,
            fast_interval_seconds=self.fast_interval_seconds,
        )

    @property
    def tags(self) -> tuple[str, ...]:
        return tuple(tag.strip() for tag in self.decision_tags.split(",") if tag.strip())

    def daily_dir(self, day: str) -> Path:
        """当天档案目录（plan §2.2）。"""
        return self.results_dir / "daily" / day

    def turn_ledger_path(self) -> Path:
        """真实用户轮次账本（plan §5.6）。"""
        return self.results_dir / "user_turns.jsonl"


@lru_cache
def get_settings() -> Settings:
    """进程内单例配置。"""
    return Settings()
