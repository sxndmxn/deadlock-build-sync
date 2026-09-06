import json
from dataclasses import asdict, replace
from datetime import UTC, datetime

import pytest

import deadlock_build_sync.api as api_module
import deadlock_build_sync.snapshot as snapshot_module
import tests.service_fake_api as fake_api_module
from deadlock_build_sync.build_evidence import (
    TierPolicyEvidence,
)
from deadlock_build_sync.service import GeneratedGuides, GuideError, generate_guides
from deadlock_build_sync.snapshot import sha256_json
from deadlock_build_sync.value_validation import (
    require_object_dict,
    require_object_rows,
)
from tests.service_evidence_fixtures import build_evidence
from tests.service_fake_api import FakeApi, ability_rows, duration_points


def _json_default(value: object) -> object:
    if isinstance(value, (set, frozenset)):
        return sorted(value, key=repr)
    raise TypeError(f"cannot normalize {type(value).__name__}")


def _assert_matchup_context(generated: GeneratedGuides) -> None:
    context = generated.contexts[0]
    matchups = require_object_dict(context["matchups"])
    same_lane = require_object_rows(matchups["same_lane"])
    whole_enemy_team = require_object_rows(matchups["whole_enemy_team"])
    assert [row["hero_id"] for row in same_lane] == [12]
    assert [row["hero_id"] for row in whole_enemy_team] == [12]
    assert same_lane[0]["scope"] == "same_lane"
    assert whole_enemy_team[0]["scope"] == "whole_enemy_team"


def _assert_policy_projection(generated: GeneratedGuides) -> None:
    guide = generated.guides[0]
    policy = generated.policies[0]
    assert guide.snapshot_id == generated.manifest.snapshot_id
    assert guide.policy_id == policy.policy_id
    assert len(policy.ability_plan) == 16
    assert all(node.kind.value == "ability" for node in policy.ability_plan)
    assert policy.nodes[0].kind.value in {"purchase", "choice"}
    assert {abstention.reason.value for abstention in policy.abstentions} == {
        "inadequate_support_or_overlap",
        "telemetry_failure",
        "unclear_threat",
    }
    assert [row.name for row in guide.categories[-4:]] == [
        f"ITEM POOL | TIER {tier}" for tier in range(1, 5)
    ]
    assert [len(row.items) for row in guide.categories[-4:]] == [8] * 4
    assert [
        item.item_id
        for row in guide.categories
        if not row.optional
        for item in row.items
    ] == [item.item_id for item in guide.core_purchase_items]
    assert not guide.categories[0].optional
    assert guide.build_tag_ids == (10, 301, 4)
    assert guide.build_tag_classes == (
        "ability_1",
        "item_3_1",
        "citadel_build_tag_damage",
    )
    assert guide.build_tag_labels == ("Ability 1", "Tier 3 Item 1", "Damage")


def _assert_strategy_context(generated: GeneratedGuides) -> None:
    context = generated.contexts[0]
    projection = require_object_dict(context["projection"])
    build = require_object_dict(projection["build"])
    ending = require_object_dict(context["ending_duration_profile"])
    ability_policy = require_object_dict(context["ability_policy"])
    ability_steps = require_object_rows(ability_policy["steps"])
    assert build["tag_ids"] == [10, 301, 4]
    assert ending["estimand"] == "ending_duration_profile"
    assert ability_steps[0]["earliest_legal_level"] == 1


def test_rejects_selected_hero_without_complete_ability_path() -> None:
    api = FakeApi(ability_rows=[], duration_points=duration_points())
    evidence = build_evidence(api)

    with pytest.raises(GuideError, match="reached-state ability projection"):
        generate_guides(
            api,
            build_evidence=evidence,
            account_id=123,
            hero_query="Kelvin",
            all_heroes=False,
        )


def test_rejects_observed_imbue_target_outside_current_hero_kit() -> None:
    api = FakeApi(ability_rows=ability_rows(), duration_points=duration_points())
    catalog = build_evidence(api)
    hero = catalog.heroes[12]
    items = tuple(
        replace(
            item,
            imbue_target_ability_id=999,
            imbue_target_ability="Stale Ability",
            imbue_target_matches=60,
            imbue_observations=80,
            imbue_target_share=0.75,
        )
        if item.item_id == 100
        else item
        for item in hero.items
    )
    evidence = replace(catalog, heroes={12: replace(hero, items=items)})

    with pytest.raises(GuideError, match="not a current hero ability"):
        generate_guides(
            api,
            build_evidence=evidence,
            account_id=123,
            hero_query="Kelvin",
            all_heroes=False,
        )


def test_incomplete_duration_curve_abstains_without_discarding_policy() -> None:
    api = FakeApi(
        ability_rows=ability_rows(),
        duration_points=duration_points()[1:],
    )

    generated = generate_guides(
        api,
        build_evidence=build_evidence(api),
        account_id=123,
        hero_query=None,
        all_heroes=True,
    )

    assert len(generated.guides) == 1
    assert generated.skipped_heroes == ()
    ending = require_object_dict(generated.contexts[0]["ending_duration_profile"])
    assert ending["status"] == "abstained"
    assert ending["strongest_phase"] == "UNAVAILABLE"
    assert any(
        "ending-duration profile" in abstention.detail
        for abstention in generated.policies[0].abstentions
    )


def test_generated_guide_is_snapshot_bound_policy_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generated_at = datetime(2026, 1, 2, tzinfo=UTC)

    class FixedDatetime:
        @staticmethod
        def now(_timezone: object) -> datetime:
            return generated_at

    monkeypatch.setattr(api_module, "datetime", FixedDatetime)
    monkeypatch.setattr(snapshot_module, "datetime", FixedDatetime)
    monkeypatch.setattr(fake_api_module, "datetime", FixedDatetime)
    api = FakeApi(ability_rows=ability_rows(), duration_points=duration_points())
    generated = generate_guides(
        api,
        build_evidence=build_evidence(api),
        account_id=123,
        hero_query="Kelvin",
        all_heroes=False,
    )

    normalized = json.loads(json.dumps(asdict(generated), default=_json_default))
    assert sha256_json(normalized) == (
        "3092bea459dbaeda02a0b6bafea276a9f5a2bb1826d1dd0806a10c0c331c0514"
    )
    assert len(generated.guides) == len(generated.policies) == 1
    assert api.counter_stat_calls == [True, False]
    _assert_matchup_context(generated)
    _assert_policy_projection(generated)
    _assert_strategy_context(generated)


def test_supported_item_paths_create_separate_guides_and_ability_queries() -> None:
    api = FakeApi(ability_rows=ability_rows(), duration_points=duration_points())
    catalog = build_evidence(api)
    base = replace(
        catalog.heroes[12],
        path_id="control",
        path_label="Control Core",
        signature_item_ids=(100, 101),
    )
    second_policy = replace(
        base.core_policy,
        backbone_item_ids=(102, 103, 202, 203),
        default_item_ids=(102, 103, 202, 203, 302, 303, 402, 403),
    )
    second = replace(
        base,
        path_id="damage",
        path_label="Damage Core",
        signature_item_ids=(102, 103),
        core_policy=second_policy,
        tier_policy=TierPolicyEvidence({
            tier: tuple(
                item.item_id
                for item in base.items
                if item.tier == tier
                and item.item_id not in set(second_policy.default_item_ids)
            )
            for tier in range(1, 5)
        }),
    )
    catalog = replace(
        catalog,
        heroes={12: base},
        hero_builds={12: (base, second)},
    )

    generated = generate_guides(
        api,
        build_evidence=catalog,
        account_id=123,
        hero_query="Kelvin",
        all_heroes=False,
    )

    assert [guide.path_id for guide in generated.guides] == ["control", "damage"]
    assert [policy.path_id for policy in generated.policies] == ["control", "damage"]
    assert api.ability_filter_calls == [
        (),
        (100, 101, 200, 201),
        (102, 103, 202, 203),
    ]
    ability_path = generated.guides[0].ability_path
    assert ability_path is not None
    assert ability_path.filter_item_ids == (
        100,
        101,
        200,
        201,
    )
