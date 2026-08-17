import pytest

from deadlock_build_sync.ranks import (
    DEFAULT_RANK_RANGE,
    Rank,
    RankDivision,
    RankRange,
    RankTier,
)


def test_default_range_is_emissary_one_through_eternus_five() -> None:
    assert DEFAULT_RANK_RANGE.minimum == Rank(
        RankTier.EMISSARY,
        RankDivision.ONE,
    )
    assert DEFAULT_RANK_RANGE.maximum == Rank(
        RankTier.ETERNUS,
        RankDivision.FIVE,
    )
    assert DEFAULT_RANK_RANGE.api_parameters == {
        "min_average_badge": 71,
        "max_average_badge": 115,
    }
    assert DEFAULT_RANK_RANGE.label == "Emissary I–Eternus V"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("oracle-iii", Rank(RankTier.ORACLE, RankDivision.THREE)),
        ("Phantom_V", Rank(RankTier.PHANTOM, RankDivision.FIVE)),
        ("ascendant 6", Rank(RankTier.ASCENDANT, RankDivision.SIX)),
    ],
)
def test_parses_symbolic_rank_names(raw: str, expected: Rank) -> None:
    assert Rank.parse(raw) == expected


def test_rejects_an_inverted_range() -> None:
    minimum = Rank(RankTier.ETERNUS, RankDivision.ONE)
    maximum = Rank(RankTier.ORACLE, RankDivision.SIX)
    with pytest.raises(ValueError, match="exceeds"):
        RankRange(minimum=minimum, maximum=maximum)
