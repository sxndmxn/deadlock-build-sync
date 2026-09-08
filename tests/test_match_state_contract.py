from __future__ import annotations

import pytest

from deadlock_build_sync.recommendation_state import DecisionState, RecommendationError
from tests.recommendation_fixtures import decision_state_document


@pytest.mark.parametrize(
    "economy",
    [
        {},
        {"personal_net_worth": 8000},
        {"lobby_net_worths": [10000] * 11},
        {
            "personal_net_worth": 8000,
            "lobby_net_worths": [10000] * 12,
            "observed_at_s": 0,
        },
    ],
)
def test_incomplete_or_stale_economy_disables_wealth_conditions(
    economy: dict[str, object],
) -> None:
    document = decision_state_document()
    document["clock_s"] = 301
    document["economy"] = economy
    current = DecisionState.from_document(document)
    assert current.economy is not None
    assert current.economy.relative_wealth(current.clock_s) is None


@pytest.mark.parametrize(
    "economy",
    [
        [],
        {"unknown": 1},
        {"lobby_net_worths": None},
        {"lobby_net_worths": [1] * 13},
        {"personal_net_worth": -1},
        {"observed_at_s": True},
        {"lobby_net_worths": [False]},
    ],
)
def test_malformed_economy_is_an_error(economy: object) -> None:
    document = decision_state_document()
    document["economy"] = economy
    with pytest.raises(RecommendationError):
        DecisionState.from_document(document)


def test_state_accepts_combined_choices_explicit_placements_and_economy() -> None:
    document = decision_state_document()
    document.update({
        "path_id": "frozen-core",
        "selected_optional_items": [7, 8],
        "placement_overrides": {"7": 2, "8": 3},
        "core_substitution_item_id": 7,
        "enemy_observed_at_s": 299,
        "economy": {
            "personal_net_worth": 8000,
            "lobby_net_worths": [10000] * 12,
            "observed_at_s": 299,
        },
    })
    current = DecisionState.from_document(document)
    assert current.selected_optional_items == (7, 8)
    assert current.placement_overrides == {7: 2, 8: 3}
    assert current.core_substitution_item_id == 7
    assert current.economy is not None
    assert current.economy.relative_wealth(300) == 0.8
