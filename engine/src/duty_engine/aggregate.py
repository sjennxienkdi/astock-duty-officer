"""stance 聚合（plan §5.2）与五词序轴（plan §2.4）。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum


class Stance(StrEnum):
    """五个 stance 词冻结，值即中文词本身。"""

    CLEAR = "清仓"
    TRIM = "减仓"
    HOLD = "持有"
    OPEN = "建仓"
    ADD = "加仓"


STANCE_RANK: dict[Stance, int] = {
    Stance.CLEAR: -2,
    Stance.TRIM: -1,
    Stance.HOLD: 0,
    Stance.OPEN: 1,
    Stance.ADD: 2,
}

RANK_STANCE: dict[int, Stance] = {rank: stance for stance, rank in STANCE_RANK.items()}


def parse_stance(word: str) -> Stance:
    """按冻结词表解析 stance，同义词一律不认。"""
    try:
        return Stance(word)
    except ValueError as exc:
        raise ValueError(f"stance 只允许五词，收到 {word!r}") from exc


@dataclass(frozen=True)
class Aggregated:
    """一只标的的聚合结果。"""

    stance: Stance
    conflict: bool
    votes: int


def median_toward_zero(ranks: Sequence[int]) -> int:
    """中位数；偶数取居中两值中靠近 0 的一侧（更保守）。"""
    ordered = sorted(ranks)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    low, high = ordered[mid - 1], ordered[mid]
    return low if abs(low) <= abs(high) else high


def aggregate(stances: dict[str, list[Stance]]) -> dict[str, Aggregated]:
    """同码多实例聚合：极差 ≤1 取中位数，≥2 回落持有并记冲突。"""
    result: dict[str, Aggregated] = {}
    for code, votes in stances.items():
        if not votes:
            continue
        ranks = [STANCE_RANK[stance] for stance in votes]
        if max(ranks) - min(ranks) >= 2:
            result[code] = Aggregated(Stance.HOLD, conflict=True, votes=len(votes))
            continue
        result[code] = Aggregated(
            RANK_STANCE[median_toward_zero(ranks)], conflict=False, votes=len(votes)
        )
    return result
