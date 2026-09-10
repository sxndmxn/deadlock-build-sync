"""Rank history and outcome evidence must remain complete and internally valid."""

from __future__ import annotations

from copy import deepcopy

import pytest

from deadlock_build_sync.artifacts import ArtifactError
from deadlock_build_sync.build_evidence_discovery import validate_discovery
from deadlock_build_sync.build_support import OutcomeEvidence, outcome_limitations
from deadlock_build_sync.hero_cohort import HeroCohort, calculate_rank_cutoffs
from deadlock_build_sync.value_validation import require_object_dict
from tests.discovery_fixtures import make_discovery_record, make_hero_cohort


@pytest.mark.parametrize(
    ("minimum", "expected"),
    [(11, (11,)), (16, (16, 11)), (21, (21, 11)), (75, (75, 61, 51, 41, 31, 21, 11))],
)
def test_rank_expansion_boundaries(minimum: int, expected: tuple[int, ...]) -> None:
    assert calculate_rank_cutoffs(minimum, 115, "auto") == expected
    assert calculate_rank_cutoffs(minimum, 115, "off") == (minimum,)


@pytest.mark.parametrize(
    ("minimum", "maximum", "mode"),
    [
        (10, 115, "auto"),
        (17, 115, "auto"),
        (71, 61, "auto"),
        (71, 117, "off"),
        (71, 115, "on"),
    ],
)
def test_invalid_rank_ranges_fail(minimum: int, maximum: int, mode: str) -> None:
    with pytest.raises(ValueError, match=r"valid|exceed|rank"):
        calculate_rank_cutoffs(minimum, maximum, mode)


def test_hero_cohort_round_trip_preserves_effective_range() -> None:
    row = make_hero_cohort()
    cohort = HeroCohort.parse(row)
    assert cohort.as_dict() == row
    assert cohort.rank_range.minimum.badge_id == 61
    assert cohort.rank_range.maximum.badge_id == 115


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("minimum_badge", 51),
        ("maximum_badge", 61),
        ("rank_expansion", "off"),
        ("expansion_history", []),
        ("expansion_history", None),
    ],
)
def test_hero_cohort_rejects_inconsistent_ranges(key: str, value: object) -> None:
    with pytest.raises(ArtifactError):
        HeroCohort.parse({**make_hero_cohort(), key: value})


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("minimum_badge", 51),
        ("maximum_badge", 114),
        ("supported_builds", 1),
        ("reason", "better wins"),
        ("candidate_count", -1),
    ],
)
def test_hero_history_cannot_change_bounds_or_expand_after_support(
    key: str, value: object
) -> None:
    row = make_hero_cohort()
    history = HeroCohort.parse(row).expansion_history
    history[0][key] = value
    with pytest.raises(ArtifactError):
        HeroCohort.parse(row)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("wins", 201),
        ("win_rate", 0.5),
        ("win_rate", True),
        ("win_lower_95", float("nan")),
        ("win_p_greater_half", 2),
        ("joint_lift", -1),
        ("adjusted", None),
    ],
)
def test_malformed_outcome_counts_and_probabilities_fail(
    field: str, value: object
) -> None:
    row = require_object_dict(make_discovery_record([1, 2, 3], [1, 2, 3])["selection"])
    row[field] = value
    with pytest.raises(ArtifactError):
        OutcomeEvidence.parse(row)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("core_overlap", 201),
        ("overlap_share", 0.75),
        ("difference", None),
        ("lower_95", None),
        ("standard_error", -1),
    ],
)
def test_malformed_adjusted_estimates_fail(field: str, value: object) -> None:
    row = require_object_dict(make_discovery_record([1, 2, 3], [1, 2, 3])["selection"])
    require_object_dict(row["adjusted"])[field] = value
    with pytest.raises(ArtifactError):
        OutcomeEvidence.parse(row)


def test_absent_validation_keeps_supported_frozen_identity() -> None:
    row = make_discovery_record([1, 2, 3], [1, 2, 3])
    validation = deepcopy(require_object_dict(row["validation"]))
    validation.update({"owners": 0, "wins": 0, "win_rate": None})
    require_object_dict(validation["adjusted"]).update({
        "core_overlap": 0,
        "overlap_share": 0.0,
        "difference": None,
        "lower_95": None,
    })
    row.update({
        "validation": validation,
        "evidence_status": "observed",
        "evidence_limitations": outcome_limitations(validation),
        "order_validation": {
            "owners": 0,
            "ordered_owners": 0,
            "share": 0,
            "passes": False,
        },
    })
    validate_discovery(row, (1, 2, 3), (1, 2, 3))
    row["evidence_status"] = "outcome_supported"
    with pytest.raises(ArtifactError, match="outcome and overlap"):
        validate_discovery(row, (1, 2, 3), (1, 2, 3))


@pytest.mark.parametrize("limitations", [[], [None], [""], None])
def test_observed_status_requires_explicit_limits(limitations: object) -> None:
    row = make_discovery_record([1, 2, 3], [1, 2, 3])
    row.update({"evidence_status": "observed", "evidence_limitations": limitations})
    with pytest.raises(ArtifactError, match="limitations"):
        validate_discovery(row, (1, 2, 3), (1, 2, 3))
