import pytest

from deadlock_build_sync.ranks import (
    DEFAULT_RANK_RANGE,
    Rank,
    RankDivision,
    RankRange,
    RankTier,
)


def test_default_range_is_phantom_one_through_eternus_six() -> None:
    assert DEFAULT_RANK_RANGE.minimum == Rank(
        RankTier.PHANTOM,
        RankDivision.ONE,
    )
    assert DEFAULT_RANK_RANGE.maximum == Rank(
        RankTier.ETERNUS,
        RankDivision.SIX,
    )
    assert DEFAULT_RANK_RANGE.api_parameters == {
        "min_average_badge": 91,
        "max_average_badge": 116,
    }
    assert DEFAULT_RANK_RANGE.label == "Phantom I–Eternus VI"


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
    with pytest.raises(ValueError, match="exceeds"):
        RankRange(
            minimum=Rank(RankTier.ETERNUS, RankDivision.ONE),
            maximum=Rank(RankTier.ORACLE, RankDivision.SIX),
        )
