"""盘中三判定与调频（plan §5.5 / §7）。触发条件是规则，不是 LLM；保护线只读冻结值。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from duty_engine.clock import ensure_shanghai
from duty_engine.freeze import Plan
from duty_engine.storage import require_int

VERDICT_KINDS = ("move", "volume", "protect")


@dataclass(frozen=True)
class Snapshot:
    """一次行情快照。价格单位：分。"""

    code: str
    name: str
    at: datetime
    price_cents: int
    volume_lots: int
    prev_close_cents: int

    def __post_init__(self) -> None:
        ensure_shanghai(self.at)
        require_int("price_cents", self.price_cents)
        require_int("volume_lots", self.volume_lots)


@dataclass(frozen=True)
class MonitorConfig:
    """三判定阈值与调频参数（plan §5.5）。倍数一律用万分比：2.5 倍 = 25000。"""

    move_trigger_bps: int = 300
    volume_multiple_bps: int = 25_000
    slow_interval_seconds: int = 300
    fast_interval_seconds: int = 60
    fast_release_rounds: int = 3

    def __post_init__(self) -> None:
        require_int("move_trigger_bps", self.move_trigger_bps)


@dataclass(frozen=True)
class Verdict:
    """一条判定结论：只记现象，不做归因。"""

    code: str
    kind: str
    detail: str


def judge(
    snapshot: Snapshot, plan: Plan, vma5_lots: Mapping[str, int], config: MonitorConfig
) -> Verdict | None:
    """单标的三判定，命中任一即返回；保护线只读 `Plan` 里的冻结值。"""
    change = abs(snapshot.price_cents - snapshot.prev_close_cents)
    move_bps = change * 10_000 // snapshot.prev_close_cents
    if move_bps >= config.move_trigger_bps:
        return Verdict(snapshot.code, "move", f"|Δ|={move_bps}bps ≥ {config.move_trigger_bps}bps")
    vma5 = vma5_lots.get(snapshot.code, 0)
    if vma5 and snapshot.volume_lots * 10_000 >= vma5 * config.volume_multiple_bps:
        multiple = snapshot.volume_lots * 10_000 // vma5
        detail = f"量比 {multiple}bps ≥ {config.volume_multiple_bps}bps（5日均量 {vma5} 手）"
        return Verdict(snapshot.code, "volume", detail)
    target = next((t for t in plan.targets if t.code == snapshot.code), None)
    if target is not None and snapshot.price_cents <= target.protect_trigger_cents:
        return Verdict(
            snapshot.code,
            "protect",
            f"price={snapshot.price_cents} ≤ 冻结触发线 {target.protect_trigger_cents}",
        )
    return None


@dataclass(frozen=True)
class Frequency:
    """盯盘轮询频率。调频与回落都由引擎执行。"""

    interval_seconds: int
    fast: bool
    quiet_rounds: int

    @property
    def label(self) -> str:
        return "1min" if self.fast else "5min"


def initial_frequency(config: MonitorConfig) -> Frequency:
    """开盘默认低频。"""
    return Frequency(config.slow_interval_seconds, fast=False, quiet_rounds=0)


def step_frequency(freq: Frequency, triggered: bool, config: MonitorConfig) -> Frequency:
    """命中阈值 → 高频；连续 N 轮阈值内 → 回落低频。"""
    if triggered:
        return Frequency(config.fast_interval_seconds, fast=True, quiet_rounds=0)
    if not freq.fast:
        return freq
    quiet = freq.quiet_rounds + 1
    if quiet >= config.fast_release_rounds:
        return Frequency(config.slow_interval_seconds, fast=False, quiet_rounds=0)
    return Frequency(config.fast_interval_seconds, fast=True, quiet_rounds=quiet)
