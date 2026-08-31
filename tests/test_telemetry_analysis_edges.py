from __future__ import annotations

import math

import pytest

from deadlock_build_sync import telemetry_analysis
from deadlock_build_sync.snapshot import MatchMode
from deadlock_build_sync.telemetry import (
    CandidateEffect,
    CohortWindow,
    LandmarkObservation,
    StateFeature,
    TelemetryError,
)


def test_candidate_estimate_and_selection_handle_no_support() -> None:
    assert CandidateEffect("empty", 0, 0).estimate == 0.0
    assert (
        telemetry_analysis.select_then_estimate(
            (CandidateEffect("a", 1, 1),),
            (),
            minimum_support=2,
        )
        is None
    )
    assert (
        telemetry_analysis.select_then_estimate(
            (CandidateEffect("a", 2, 2),),
            (),
            minimum_support=2,
        )
        is None
    )
    assert (
        telemetry_analysis.select_then_estimate(
            (CandidateEffect("a", 2, 2),),
            (CandidateEffect("a", 1, 1),),
            minimum_support=2,
        )
        is None
    )


@pytest.mark.parametrize(
    "abilities",
    [None, [], list(range(17)), [1, "2"], [99], [1, 1, 1, 1, 1]],
)
def test_ability_path_validation_rejects_bad_shape_ids_and_rank_counts(
    abilities: object,
) -> None:
    assert telemetry_analysis._validated_ability_path(abilities, {1, 2}) is None
    assert telemetry_analysis._validated_ability_path([1, 2], {1, 2}) == (1, 2)


def test_prefix_aggregation_counts_complete_paths_and_filters_low_support() -> None:
    complete = [1, 2, 3, 4] * 4
    report = telemetry_analysis.aggregate_ability_prefixes(
        [
            {"abilities": complete, "matches": 2},
            {"abilities": [1, 2], "matches": 0},
            {"abilities": [1, 2], "matches": 1},
        ],
        valid_ability_ids={1, 2, 3, 4},
        all_appearances=3,
        minimum_path_support=2,
    )
    assert report.valid_telemetry_appearances == 3
    assert report.complete_path_appearances == 2
    assert report.retained_path_appearances == 2


def test_landmarks_return_zero_for_empty_risk_set() -> None:
    estimates = telemetry_analysis.estimate_landmarks(
        (LandmarkObservation(1, 10, won=True),),
        (20,),
    )
    assert estimates[0].at_risk == 0
    assert estimates[0].estimate == 0.0


def test_state_feature_rejects_negative_staleness() -> None:
    with pytest.raises(TelemetryError, match="invalid staleness"):
        StateFeature("state", 1, "observed", 0, -1).validate_for(0)


@pytest.mark.parametrize(
    ("window", "message"),
    [
        (CohortWindow(2, 1, 0, 10, 1), "rank range"),
        (CohortWindow(1, 2, 10, 10, 1), "time range"),
        (CohortWindow(1, 2, 0, 10, -1), "support"),
        (CohortWindow(1, 2, 0, 10, 1, epoch_identity=" "), "epoch identity"),
    ],
)
def test_cohort_window_rejects_invalid_bounds(
    window: CohortWindow,
    message: str,
) -> None:
    with pytest.raises(TelemetryError, match=message):
        telemetry_analysis._validate_cohort_window(window, None)


def test_sparse_cohort_stops_on_support_and_regime_change() -> None:
    first = CohortWindow(5, 6, 10, 20, 20)
    later = CohortWindow(4, 7, 0, 30, 30)
    assert telemetry_analysis.widen_sparse_cohort(
        (first, later),
        minimum_support=10,
    ) == (first,)

    changed = CohortWindow(
        4,
        7,
        0,
        30,
        30,
        match_mode=MatchMode.UNRANKED,
    )
    assert telemetry_analysis.widen_sparse_cohort(
        (replace_support(first, 1), changed),
        minimum_support=10,
    ) == (replace_support(first, 1),)
    assert telemetry_analysis.widen_sparse_cohort((), minimum_support=10) == ()


def replace_support(window: CohortWindow, support: int) -> CohortWindow:
    return CohortWindow(
        window.minimum_badge,
        window.maximum_badge,
        window.start_timestamp,
        window.end_timestamp,
        support,
        window.match_mode,
        window.epoch_identity,
    )


@pytest.mark.parametrize(
    ("alpha", "comparisons"),
    [(0.0, 1), (1.0, 1), (0.05, 0)],
)
def test_multiplicity_rejects_invalid_inputs(alpha: float, comparisons: int) -> None:
    with pytest.raises(TelemetryError, match="multiplicity"):
        telemetry_analysis.bonferroni_alpha(alpha, comparisons)
    assert telemetry_analysis.bonferroni_alpha(0.05, 5) == pytest.approx(0.01)


def test_effective_support_and_standard_error_handle_empty_inputs() -> None:
    assert telemetry_analysis.effective_support(()) == 0.0
    assert telemetry_analysis.effective_support((1.0, 1.0)) == 2.0
    assert telemetry_analysis.standard_error(0.5, 0) == math.inf
    assert telemetry_analysis.standard_error(0.5, 100) == pytest.approx(0.05)
