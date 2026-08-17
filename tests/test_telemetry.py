from typing import Any

import pytest

from deadlock_build_sync.mechanics import ItemGraph
from deadlock_build_sync.snapshot import EvidenceUnit, MatchMode, OutcomePolicy
from deadlock_build_sync.telemetry import (
    AbilityDecisionReport,
    CandidateEffect,
    CohortWindow,
    CompetingEvent,
    FirstPurchaseObservation,
    InventoryEvent,
    InventoryEventKind,
    LandmarkObservation,
    MatchupPair,
    MatchupScope,
    OutcomeRow,
    PurchaseEvent,
    StateFeature,
    TelemetryError,
    aggregate_ability_prefixes,
    descriptive_rate,
    empirical_bayes_rate,
    estimate_item_adoption,
    estimate_landmarks,
    estimate_matchups,
    first_purchase_cumulative_incidence,
    outcome_is_eligible,
    reconstruct_inventory_events,
    select_then_estimate,
    validated_purchase_net_worth,
    widen_sparse_cohort,
)


def graph_assets() -> list[dict[str, Any]]:
    return [
        {
            "id": 1,
            "class_name": "component",
            "name": "Component",
            "cost": 500,
            "component_items": [],
            "item_slot_type": "spirit",
            "item_tier": 1,
            "shopable": True,
            "disabled": False,
        },
        {
            "id": 2,
            "class_name": "upgrade",
            "name": "Upgrade",
            "cost": 1250,
            "component_items": ["component"],
            "item_slot_type": "spirit",
            "item_tier": 2,
            "shopable": True,
            "disabled": False,
        },
    ]


def test_outcome_eligibility_precedes_won_value() -> None:
    policy = OutcomePolicy()

    assert outcome_is_eligible(OutcomeRow(won=False), policy)
    assert not outcome_is_eligible(OutcomeRow(won=True, penalized=True), policy)
    assert not outcome_is_eligible(OutcomeRow(won=True, party_penalized=True), policy)
    assert not outcome_is_eligible(OutcomeRow(won=True, rewarded=False), policy)
    assert not outcome_is_eligible(OutcomeRow(won=True, new_player=True), policy)


def test_adoption_deduplicates_rebuys_but_keeps_events_and_accounts() -> None:
    appearances = {(1, 0), (1, 1), (2, 0)}
    events = (
        PurchaseEvent(1, 0, 7, 100, 200),
        PurchaseEvent(1, 0, 7, 100, 400),
        PurchaseEvent(2, 0, 7, 100, 500),
        PurchaseEvent(9, 0, 8, 100, 500),
    )

    result = estimate_item_adoption(100, appearances, events)

    assert result.first_ownerships == 2
    assert result.purchase_events == 3
    assert result.unique_accounts == 1
    assert result.adoption == 2 / 3
    assert result.unit == EvidenceUnit.ELIGIBLE_APPEARANCE


def test_opening_net_worth_quarantines_final_snapshot_fallback() -> None:
    event = PurchaseEvent(1, 0, None, 1, 120, net_worth=20_000, final_net_worth=20_000)
    with pytest.raises(TelemetryError, match="final-snapshot"):
        validated_purchase_net_worth(event)
    assert (
        validated_purchase_net_worth(
            PurchaseEvent(
                1,
                0,
                None,
                1,
                120,
                preceding_net_worth=900,
                preceding_time_s=100,
            )
        )
        == 900
    )
    assert validated_purchase_net_worth(PurchaseEvent(1, 0, None, 1, 120)) is None


def test_first_purchase_hazard_uses_all_competing_events() -> None:
    points = first_purchase_cumulative_incidence((
        FirstPurchaseObservation((1, 0), 10, CompetingEvent.PURCHASE),
        FirstPurchaseObservation((1, 1), 10, CompetingEvent.SUBSTITUTE),
        FirstPurchaseObservation((2, 0), 20, CompetingEvent.PURCHASE),
        FirstPurchaseObservation((2, 1), 30, CompetingEvent.GAME_END),
    ))

    assert points[0].at_risk == 4
    assert points[0].cause_specific_hazard == 0.25
    assert points[0].cumulative_incidence == 0.25
    assert points[1].at_risk == 2
    assert points[1].cumulative_incidence == 0.5


def test_equal_time_upgrade_credit_precedes_consumption_event() -> None:
    graph = ItemGraph.from_assets(graph_assets())
    reconstructed = reconstruct_inventory_events(
        graph,
        (
            InventoryEvent(10, 0, InventoryEventKind.PURCHASE, 1),
            InventoryEvent(20, 0, InventoryEventKind.SELL, 1),
            InventoryEvent(20, 1, InventoryEventKind.PURCHASE, 2),
        ),
    )

    assert reconstructed[1].classification == "upgrade_purchase"
    assert reconstructed[1].cash_required == 750
    assert reconstructed[2].classification == "upgrade_consumption"
    assert reconstructed[2].owned_after == (2,)


def test_uncertainty_shrinkage_and_disjoint_selection() -> None:
    rate = descriptive_rate(
        wins=6,
        observations=10,
        baseline=0.5,
        unit=EvidenceUnit.HERO_APPEARANCE,
    )
    assert rate.label == "observational descriptive rate"
    assert rate.interval[0] < rate.estimate < rate.interval[1]
    assert (
        abs(empirical_bayes_rate(1, 2, baseline=0.5, prior_strength=10) - 0.5)
        < abs(0.5 - 0.5) + 1e-12
    )
    held_out = select_then_estimate(
        (
            CandidateEffect("a", 9, 10),
            CandidateEffect("b", 8, 10),
        ),
        (
            CandidateEffect("a", 4, 10),
            CandidateEffect("b", 7, 10),
        ),
        minimum_support=5,
    )
    assert held_out == CandidateEffect("a", 4, 10)


def test_sparse_cohort_widens_monotonically_without_crossing_regime() -> None:
    windows = (
        CohortWindow(91, 96, 100, 200, 5),
        CohortWindow(85, 102, 90, 200, 12),
        CohortWindow(
            79,
            108,
            80,
            200,
            100,
            match_mode=MatchMode.UNRANKED,
        ),
    )

    assert widen_sparse_cohort(windows, minimum_support=20) == windows[:2]
    invalid_windows = (
        CohortWindow(91, 96, 100, 200, 5),
        CohortWindow(92, 95, 100, 200, 20),
    )
    with pytest.raises(TelemetryError, match="monotonically widen"):
        widen_sparse_cohort(invalid_windows, minimum_support=20)


def test_prefix_aggregation_keeps_variable_paths_and_denominators() -> None:
    report: AbilityDecisionReport = aggregate_ability_prefixes(
        [
            {"abilities": [10, 20], "matches": 60},
            {"abilities": [10, 30, 20], "matches": 40},
            {"abilities": [99], "matches": 100},
        ],
        valid_ability_ids={10, 20, 30, 40},
        all_appearances=200,
    )

    assert report.all_appearances == 200
    assert report.valid_telemetry_appearances == 100
    assert report.complete_path_appearances == 0
    assert report.decisions[0].next_probabilities == {10: 1.0}
    after_ten = next(
        decision for decision in report.decisions if decision.prefix == (10,)
    )
    assert after_ten.reached == 100
    assert after_ten.next_probabilities == {20: 0.6, 30: 0.4}


def test_lane_and_team_matchups_do_not_collide() -> None:
    pairs = (
        *(
            MatchupPair(
                1,
                (1, 0),
                enemy_id,
                won=enemy_id % 2 == 0,
                scope=MatchupScope.WHOLE_ENEMY_TEAM,
            )
            for enemy_id in range(10, 16)
        ),
        MatchupPair(
            1,
            (1, 0),
            10,
            won=False,
            scope=MatchupScope.SAME_LANE,
        ),
    )

    team = estimate_matchups(
        pairs,
        scope=MatchupScope.WHOLE_ENEMY_TEAM,
        baseline=0.5,
        prior_strength=10,
    )
    lane = estimate_matchups(
        pairs,
        scope=MatchupScope.SAME_LANE,
        baseline=0.5,
        prior_strength=10,
    )

    assert sum(row.pair_rows for row in team) == 6
    assert len({pair.focal_appearance for pair in pairs}) == 1
    assert lane[0].scope == MatchupScope.SAME_LANE


def test_landmarks_condition_only_on_still_active_games() -> None:
    estimates = estimate_landmarks(
        (
            LandmarkObservation(1, 1000, won=True),
            LandmarkObservation(2, 2000, won=False),
            LandmarkObservation(3, 3000, won=True),
        ),
        (1500, 2500),
    )

    assert [(estimate.landmark_s, estimate.at_risk) for estimate in estimates] == [
        (1500, 2),
        (2500, 1),
    ]


@pytest.mark.parametrize(
    ("feature", "message"),
    [
        (StateFeature("worth", 1, "final_net_worth", 0, 999), "leaks"),
        (StateFeature("enemy", 1, "enemy_seen", 11, 999), "not available"),
        (StateFeature("enemy", 1, "enemy_seen", 0, 5), "stale"),
    ],
)
def test_feature_availability_blocks_future_leakage(
    feature: StateFeature,
    message: str,
) -> None:
    with pytest.raises(TelemetryError, match=message):
        feature.validate_for(10)
