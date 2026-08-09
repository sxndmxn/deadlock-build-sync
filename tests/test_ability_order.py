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


def test_selects_default_from_all_reached_prefixes() -> None:
    selected = select_ability_path([
        path(*PATH_A, matches=100, wins=55),
        path(*PATH_B, matches=80, wins=60),
        path(*PATH_A[:-1], matches=500, wins=400),
        path(*PATH_B, matches=19, wins=19),
    ])
    assert selected is not None
    assert selected.ability_ids == PATH_A
    assert selected.matches == 199
    assert selected.pick_rate == pytest.approx(199 / 699)
    assert selected.win_rate == pytest.approx(134 / 199)
    assert selected.complete_path_matches == 199
    assert selected.decision_support[0] == 699
    assert selected.annotation == (
        "State-conditioned projection | final support 199 | observed outcome rate 67.3%"
    )


def test_ability_id_breaks_equal_support_tie_without_outcome_selection() -> None:
    selected = select_ability_path([
        path(*PATH_A, matches=50, wins=40),
        path(*PATH_B, matches=50, wins=10),
    ])
    assert selected is not None
    assert selected.ability_ids == PATH_B


def test_rejects_non_native_ability_counts() -> None:
    invalid = (1,) * 5 + (2,) * 4 + (3,) * 4 + (4,) * 3
    assert select_ability_path([path(*invalid, matches=100, wins=60)]) is None


def test_pools_equivalent_reached_states_and_keeps_sparse_legal_tail() -> None:
    selected = select_ability_path([
        path(*PATH_A, matches=3, wins=2),
        path(*PATH_A[:-1], matches=50, wins=25),
    ])

    assert selected is not None
    assert selected.ability_ids == PATH_A
    assert selected.decision_support[-1] == 3
    assert selected.selection == "MOST_SUPPORTED_LEGAL_STATE"
