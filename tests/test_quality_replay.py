import pytest

from deadlock_build_sync.quality_replay import parse_replay
from deadlock_build_sync.recommendation_state import RecommendationError
from deadlock_build_sync.value_validation import require_object_dict
from tests.quality_fixtures import make_replay_document, make_replay_row
from tests.recommendation_fixtures import make_recommendation_policy


def _parse(document: object) -> None:
    parse_replay(
        document, (make_recommendation_policy(),), cutoff=1000, evidence_id="a" * 64
    )


def test_later_replay_retains_unfinished_and_ambiguous_states() -> None:
    row = {**make_replay_row(), "ambiguous_purchase": True}
    cases = parse_replay(
        make_replay_document([row]),
        (make_recommendation_policy(),),
        cutoff=1000,
        evidence_id="a" * 64,
    )
    assert len(cases) == 1
    assert cases[0].ambiguous_purchase
    assert not cases[0].core_completed


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("match_start_timestamp", 1000, "after the frozen cutoff"),
        ("match_start_timestamp", True, "invalid match start"),
        ("feature_as_of_timestamp", 2301, "pre-decision window"),
        ("feature_as_of_timestamp", 1999, "pre-decision window"),
        ("policy_assigned_at", 2200, "before the match"),
        ("policy_id", "different", "another frozen policy"),
        ("match_group", "", "match group"),
        ("core_completed", None, "boolean core_completed"),
        ("observed_action", "invented", "observed action"),
        ("observed_item_id", None, "observed item"),
        ("observed_action", "save", "only observed buys"),
    ],
)
def test_replay_rejects_invalid_or_future_inputs(
    field: str, value: object, message: str
) -> None:
    with pytest.raises(RecommendationError, match=message):
        _parse(make_replay_document([{**make_replay_row(), field: value}]))


def test_replay_rejects_duplicate_and_selected_cohorts() -> None:
    with pytest.raises(RecommendationError, match="repeats"):
        _parse(make_replay_document([make_replay_row(), make_replay_row()]))
    with pytest.raises(RecommendationError, match="unfinished"):
        _parse({**make_replay_document([]), "cohort_selection": "completed_only"})
    with pytest.raises(RecommendationError, match="schema"):
        _parse({})
    with pytest.raises(RecommendationError, match="list of objects"):
        _parse({**make_replay_document([]), "cases": [None]})


def test_replay_rejects_crossed_state_identity_and_missing_observation() -> None:
    row = make_replay_row()
    require_object_dict(row["state"])["hero_id"] = 99
    with pytest.raises(RecommendationError, match="hero differs"):
        _parse(make_replay_document([row]))
    row = make_replay_row()
    require_object_dict(row["state"])["build_evidence_id"] = "b" * 64
    with pytest.raises(RecommendationError, match="another evidence"):
        _parse(make_replay_document([row]))
    row = make_replay_row()
    row.pop("observed_item_id")
    with pytest.raises(RecommendationError, match="requires observed_item_id"):
        _parse(make_replay_document([row]))
    with pytest.raises(RecommendationError, match="schema"):
        _parse({**make_replay_document([]), "schema_version": True})
