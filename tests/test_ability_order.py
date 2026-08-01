import pytest

from deadlock_build_sync.ability_order import select_ability_path


def path(*ability_ids: int, matches: int, wins: int) -> dict[str, object]:
    return {
        "abilities": list(ability_ids),
        "matches": matches,
        "wins": wins,
        "losses": matches - wins,
    }


PATH_A = (1, 2, 3, 4) * 4
PATH_B = (1, 1, 2, 2, 3, 3, 4, 4, 1, 2, 3, 4, 1, 2, 3, 4)


def test_selects_most_picked_complete_reliable_path() -> None:
    selected = select_ability_path([
        path(*PATH_A, matches=100, wins=55),
        path(*PATH_B, matches=80, wins=60),
        path(*PATH_A[:-1], matches=500, wins=400),
        path(*PATH_B, matches=19, wins=19),
    ])
    assert selected is not None
    assert selected.ability_ids == PATH_A
    assert selected.matches == 100
    assert selected.pick_rate == pytest.approx(100 / 180)
    assert selected.win_rate == pytest.approx(0.55)
    assert selected.annotation == "Path pick 55.6% | Raw WR 55.0% | 100 matches"


def test_raw_win_rate_breaks_equal_pick_rate_tie() -> None:
    selected = select_ability_path([
        path(*PATH_A, matches=50, wins=25),
        path(*PATH_B, matches=50, wins=30),
    ])
    assert selected is not None
    assert selected.ability_ids == PATH_B


def test_rejects_non_native_ability_counts() -> None:
    invalid = (1,) * 5 + (2,) * 4 + (3,) * 4 + (4,) * 3
    assert select_ability_path([path(*invalid, matches=100, wins=60)]) is None
