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
    assert selected.final_branch_support_share == pytest.approx(199 / 699)
    assert selected.observed_final_branch_outcome_rate == pytest.approx(134 / 199)
    assert selected.complete_path_matches == 199
    assert selected.decision_support[0] == 699
    assert selected.annotation == (
        "State-composed observed default • tail support n=199 • observational."
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


def test_state_composed_label_is_truthful_when_no_exact_path_was_observed() -> None:
    observed = (
        (1, 3, 3, 2, 4, 2, 4, 3, 2, 1, 4, 4, 3, 1, 2, 1),
        (1, 3, 3, 2, 1, 2, 4, 4, 2, 4, 3, 1, 2, 3, 4, 1),
        (3, 4, 1, 1, 2, 3, 4, 4, 2, 2, 3, 3, 1, 2, 1, 4),
    )
    selected = select_ability_path([
        path(*ability_ids, matches=matches, wins=matches // 2)
        for ability_ids, matches in zip(observed, (60, 60, 66), strict=True)
    ])

    assert selected is not None
    assert selected.ability_ids not in observed
    assert "State-composed observed default" in selected.annotation
    assert "complete path" not in selected.annotation.casefold()
