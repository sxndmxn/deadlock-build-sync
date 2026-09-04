from dataclasses import replace

import pytest

from deadlock_build_sync import quality
from deadlock_build_sync.quality import evaluate_policy
from deadlock_build_sync.quality_replay import ReplayCase
from deadlock_build_sync.recommendation_state import (
    Recommendation,
    RecommendationAction,
)
from deadlock_build_sync.value_validation import require_object_dict
from tests.recommendation_fixtures import (
    assets,
    build_policy,
    catalog,
    expanded_assets,
    state,
)
from tests.service_evidence_fixtures import build_evidence
from tests.service_fake_api import FakeApi, ability_rows, duration_points


def _case(**changes: object) -> ReplayCase:
    base = ReplayCase(
        build_policy().policy_id,
        "match",
        state(),
        RecommendationAction.BUY,
        1,
        core_completed=False,
        behind=True,
        ambiguous_purchase=False,
    )
    return replace(base, **changes)


def test_exact_runtime_replay_checks_component_credit_save_and_deviation() -> None:
    cases = (
        _case(),
        _case(
            state=state(liquid_souls=499),
            observed_action=RecommendationAction.SAVE,
            observed_item_id=None,
        ),
        _case(
            state=state(
                owned_items=(1,), owned_components=(1,), open_slots=8, liquid_souls=750
            ),
            observed_item_id=2,
        ),
        _case(state=state(purchases=(3,), owned_items=(3,), open_slots=8)),
        _case(
            state=state(owned_items=(2,), open_slots=8),
            observed_action=RecommendationAction.END,
            observed_item_id=None,
        ),
    )
    report = evaluate_policy(
        catalog(), build_policy(), catalog().heroes[12], cases, assets()
    )
    assert report["status"] == "unevaluated"
    assert require_object_dict(report["summary"])["actions"] == {
        "buy": 3,
        "end": 1,
        "save": 1,
    }
    assert require_object_dict(report["summary"])["illegal_buys"] == 0
    assert require_object_dict(report["summary"])["top1_action_agreement"] == 1
    assert (
        require_object_dict(require_object_dict(report["strata"])["manual_deviation"])[
            "decisions"
        ]
        == 1
    )
    assert (
        require_object_dict(require_object_dict(report["strata"])["unfinished_core"])[
            "decisions"
        ]
        == 5
    )


def test_runtime_replay_reports_slots_active_limits_and_invalid_state() -> None:
    rows = expanded_assets(active_ids=frozenset({1, 4, 5, 6, 7}))
    cases = (
        _case(
            state=state(
                owned_items=(3, 4, 5, 6, 7, 8, 9, 10, 11),
                open_slots=0,
                active_bindings=4,
            )
        ),
        _case(state=state(owned_items=(4, 5, 6, 7), open_slots=5, active_bindings=4)),
        _case(state=state(open_slots=8)),
    )
    result = evaluate_policy(
        catalog(), build_policy(), catalog().heroes[12], cases, rows
    )
    assert result["status"] == "fail"
    assert require_object_dict(result["summary"])["actions"] == {"abstain": 2}
    assert require_object_dict(result["summary"])["invalid_states"] == 1
    assert require_object_dict(result["summary"])["illegal_buys"] == 0


def test_missing_and_ambiguous_replays_never_fabricate_accuracy() -> None:
    empty = evaluate_policy(catalog(), build_policy(), catalog().heroes[12], (), [])
    ambiguous = evaluate_policy(
        catalog(),
        build_policy(),
        catalog().heroes[12],
        (_case(ambiguous_purchase=True),),
        assets(),
    )
    assert empty["status"] == "unevaluated"
    assert require_object_dict(empty["summary"])["top1_action_agreement"] is None
    assert require_object_dict(ambiguous["summary"])["top1_action_agreement"] is None
    assert require_object_dict(ambiguous["summary"])["ambiguous_decisions"] == 1


def test_training_baseline_respects_cash_owned_items_and_missing_mechanics() -> None:
    api = FakeApi(ability_rows=ability_rows(), duration_points=duration_points())
    source = build_evidence(api).heroes[12].items[0]
    evidence = replace(
        catalog().heroes[12],
        items=tuple(
            replace(source, item_id=item_id, training_adopter_matches=support)
            for item_id, support in ((999, 100), (3, 90), (1, 80), (2, 70), (4, 10))
        ),
    )
    cases = (
        _case(),
        _case(
            state=state(
                owned_items=(1,), owned_components=(1,), open_slots=8, liquid_souls=0
            ),
            observed_action=RecommendationAction.SAVE,
            observed_item_id=None,
        ),
    )
    report = evaluate_policy(catalog(), build_policy(), evidence, cases, assets())
    assert require_object_dict(report["summary"])["training_popularity_top1"] == 1


def test_replay_pass_requires_support_in_every_route_stratum() -> None:
    cases = tuple(
        _case(
            match_group=f"match-{index}",
            state=state(clock_s=clock, purchases=(3,), owned_items=(3,), open_slots=8),
        )
        for index in range(20)
        for clock in (300, 800, 1300)
    )
    report = evaluate_policy(
        catalog(), build_policy(), catalog().heroes[12], cases, assets()
    )
    assert report["status"] == "pass"
    assert "strategic superiority remains unproven" in str(report["reason"])
    opening_only = tuple(case for case in cases if case.state.clock_s == 300)
    insufficient = evaluate_policy(
        catalog(), build_policy(), catalog().heroes[12], opening_only, assets()
    )
    assert insufficient["status"] == "unevaluated"


def test_abstention_only_replay_cannot_pass_quality_checks() -> None:
    cases = tuple(
        _case(
            match_group=f"match-{index}",
            state=state(
                clock_s=clock,
                purchases=(3,),
                owned_items=(3, 4, 5, 6, 7, 8, 9, 10, 11),
                open_slots=0,
            ),
        )
        for index in range(20)
        for clock in (300, 800, 1300)
    )
    report = evaluate_policy(
        catalog(), build_policy(), catalog().heroes[12], cases, expanded_assets()
    )
    assert report["status"] == "unevaluated"
    assert require_object_dict(report["summary"])["actions"] == {"abstain": 60}


@pytest.mark.parametrize("item_id", [None, 999, 1])
def test_replay_detects_illegal_or_incorrectly_costed_runtime_buys(
    monkeypatch: pytest.MonkeyPatch,
    item_id: int | None,
) -> None:

    def invalid_buy(*_args: object) -> Recommendation:
        return Recommendation(
            RecommendationAction.BUY,
            12,
            build_policy().policy_id,
            item_id=item_id,
            incremental_cost=0,
        )

    monkeypatch.setattr(quality, "recommend", invalid_buy)
    report = evaluate_policy(
        catalog(), build_policy(), catalog().heroes[12], (_case(),), assets()
    )
    assert report["status"] == "fail"
    assert require_object_dict(report["summary"])["illegal_buys"] == 1
