"""stance 聚合（plan §5.2）断言。"""

from __future__ import annotations

import pytest

from duty_engine.aggregate import (
    STANCE_RANK,
    Aggregated,
    Stance,
    aggregate,
    median_toward_zero,
    parse_stance,
)


def test_aggregate_range_le1_median() -> None:
    assert aggregate({"000001": [Stance.HOLD, Stance.OPEN]})["000001"] == Aggregated(
        Stance.HOLD, conflict=False, votes=2
    )
    assert aggregate({"000001": [Stance.OPEN]})["000001"].stance is Stance.OPEN
    assert (
        aggregate({"000001": [Stance.OPEN, Stance.ADD, Stance.OPEN]})["000001"].stance
        is Stance.OPEN
    )
    assert aggregate({"000001": [Stance.TRIM, Stance.CLEAR]})["000001"].stance is Stance.TRIM
    assert median_toward_zero([1, 0]) == 0
    assert median_toward_zero([-1, 0]) == 0
    assert median_toward_zero([2, 1, 2]) == 2


def test_aggregate_range_ge2_falls_back_hold() -> None:
    result = aggregate({"600519": [Stance.CLEAR, Stance.HOLD, Stance.ADD]})
    assert result["600519"] == Aggregated(Stance.HOLD, conflict=True, votes=3)


def test_aggregate_all_absent_zero_day() -> None:
    assert aggregate({"000001": [], "600519": []}) == {}


def test_aggregate_conflict_never_becomes_a_trade() -> None:
    """冲突回落必须落在中性档，不能落在减仓。"""
    for votes in (
        [Stance.CLEAR, Stance.OPEN],
        [Stance.TRIM, Stance.ADD],
        [Stance.CLEAR, Stance.ADD],
    ):
        assert aggregate({"000001": votes})["000001"].stance is Stance.HOLD


def test_stance_rank_table_is_frozen() -> None:
    assert STANCE_RANK == {
        Stance.CLEAR: -2,
        Stance.TRIM: -1,
        Stance.HOLD: 0,
        Stance.OPEN: 1,
        Stance.ADD: 2,
    }


@pytest.mark.parametrize("word", ["观望", "清", "全清", "buy", ""])
def test_parse_stance_rejects_synonyms(word: str) -> None:
    with pytest.raises(ValueError):
        parse_stance(word)
