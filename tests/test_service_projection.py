from dataclasses import replace

import pytest

from deadlock_build_sync.api import HeroDurationStat
from deadlock_build_sync.hero_cohort import HeroCohort
from deadlock_build_sync.policy import BuildPolicy
from deadlock_build_sync.service import generate_guides
from deadlock_build_sync.strategy_context import (
    build_strategy_context_document,
    validate_strategy_context_document,
)
from deadlock_build_sync.value_validation import (
    require_object_dict,
    require_object_rows,
)
from tests.discovery_fixtures import hero_cohort
from tests.service_evidence_fixtures import build_evidence
from tests.service_fake_api import FakeApi, ability_rows, duration_points


def test_all_hero_queries_and_claims_use_effective_ranks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = FakeApi(ability_rows=ability_rows(), duration_points=duration_points())
    evidence = build_evidence(api)
    cohort = HeroCohort.parse(hero_cohort())
    hero = replace(evidence.heroes[12], cohort=cohort)
    evidence = replace(evidence, heroes={12: hero}, hero_builds={12: (hero,)})
    queries: list[tuple[str, int]] = []

    def abilities(client: FakeApi, **_kwargs: object) -> list[dict[str, object]]:
        queries.append(("ability", client.rank_range.minimum.badge_id))
        return ability_rows()

    def durations(
        client: FakeApi, **_kwargs: object
    ) -> dict[int, tuple[HeroDurationStat, ...]]:
        queries.append(("duration", client.rank_range.minimum.badge_id))
        return {12: duration_points()}

    def matchups(client: FakeApi, **_kwargs: object) -> list[dict[str, object]]:
        queries.append(("matchup", client.rank_range.minimum.badge_id))
        return []

    monkeypatch.setattr(FakeApi, "ability_order_stats", abilities)
    monkeypatch.setattr(FakeApi, "hero_stats_by_duration", durations)
    monkeypatch.setattr(FakeApi, "hero_counter_stats", matchups)
    generated = generate_guides(
        api,
        build_evidence=evidence,
        account_id=0,
        hero_query="Kelvin",
        all_heroes=False,
    )
    assert [(name, rank) for name, rank in queries if name == "ability"] == [
        ("ability", 61)
    ] * 2
    assert ("duration", 61) in queries and queries.count(("matchup", 61)) == 2
    assert api.rank_range.minimum.badge_id == 71
    guide = generated.guides[0]
    assert guide.rank_identity == cohort.rank_range.label
    assert guide.cohort == cohort
    assert guide.purchase_guidance is not None
    assert guide.purchase_guidance.cohort == cohort.as_dict()
    assert all(
        claim.cohort["rank_range"] == cohort.rank_range.as_dict()
        for claim in generated.policies[0].evidence
    )


def test_required_components_join_core_queue_and_leave_optional_rows() -> None:
    api = FakeApi(ability_rows=ability_rows(), duration_points=duration_points())
    parent = next(item for item in api._assets if item.get("id") == 200)
    parent["component_items"] = ["item_1_2"]

    generated = generate_guides(
        api,
        build_evidence=build_evidence(api, with_component_path=True),
        account_id=123,
        hero_query="Kelvin",
        all_heroes=False,
    )

    guide = generated.guides[0]
    assert [
        item.item_id
        for row in guide.categories
        if not row.optional
        for item in row.items
    ] == [
        100,
        101,
        102,
        200,
        201,
        300,
        301,
        400,
        401,
    ]
    assert [item.item_id for item in guide.core_items] == [
        100,
        101,
        200,
        201,
        300,
        301,
        400,
        401,
    ]
    assert 102 not in {item.item_id for item in guide.categories[1].items}
    projection = require_object_dict(generated.contexts[0]["projection"])
    categories = require_object_rows(projection["categories"])
    projected_items = [
        item
        for row in categories
        if not row["optional"]
        for item in require_object_rows(row["items"])
    ]
    assert projected_items[2]["item_id"] == 102


def test_admitted_situational_branch_reaches_policy_sidecar_and_tier_card() -> None:
    api = FakeApi(ability_rows=ability_rows(), duration_points=duration_points())
    generated = generate_guides(
        api,
        build_evidence=build_evidence(api, with_situational_branch=True),
        account_id=123,
        hero_query="Kelvin",
        all_heroes=False,
    )

    guide = generated.guides[0]
    policy = generated.policies[0]
    assert policy.entry == "situational-choice-1"
    assert BuildPolicy.from_dict(policy.as_dict()) == policy
    assert len(policy.counter_cards) == 1
    choice = next(node for node in policy.nodes if node.node_id == policy.entry)
    assert [guard.field for guard in choice.branches[0].guards] == [
        "enemy.threats",
        "enemy.lane_heroes",
        "clock_s",
        "clock_s",
    ]
    situational = next(node for node in policy.nodes if node.node_id == "situational-1")
    assert situational.next_id == "core-2"
    assert choice.branches[-1].next_id == "core-1"
    assert situational.annotation == (
        "VS: Heavy enemy healing\n"
        "WHY: Healing Reduction\n"
        "SWAP: Replaces Tier 1 Item 0\n"
        "WHEN: Before the next fight with heavy enemy healing\n"
        "SKIP: Keep default when weapon pressure matters more"
    )
    tier_item = next(item for item in guide.tiers[1] if item.item_id == 103)
    assert tier_item.annotation.startswith("SOUL WINDOW: ")
    assert "VS: " not in tier_item.annotation
    assert [row.name for row in guide.categories[-4:]] == [
        f"ITEM POOL | TIER {tier}" for tier in range(1, 5)
    ]
    assert all(row.optional for row in guide.categories[-4:])
    actions = require_object_rows(generated.contexts[0]["explainable_actions"])
    action = next(row for row in actions if row["node_id"] == "situational-1")
    contract = require_object_dict(action["conditional_contract"])
    assert contract["comparator_item"] == "Tier 1 Item 0"


def test_every_item_card_is_the_two_line_statistics_block() -> None:
    api = FakeApi(ability_rows=ability_rows(), duration_points=duration_points())
    generated = generate_guides(
        api,
        build_evidence=build_evidence(api),
        account_id=123,
        hero_query="Kelvin",
        all_heroes=False,
    )

    guide = generated.guides[0]
    cards = [
        item.annotation
        for category in guide.rendered_categories
        for item in category.items
    ]
    assert cards
    assert all(len(card.splitlines()) == 2 for card in cards)
    assert all(card.startswith("SOUL WINDOW: ") for card in cards)
    assert all(
        card.splitlines()[1].startswith("PR: ") and "| TOTAL GAMES: " in card
        for card in cards
    )
    assert all(len(card.encode("utf-8")) <= 240 for card in cards)


def test_admitted_core_alternative_is_a_non_queue_policy_card() -> None:
    api = FakeApi(ability_rows=ability_rows(), duration_points=duration_points())
    generated = generate_guides(
        api,
        build_evidence=build_evidence(api, with_core_alternative=True),
        account_id=123,
        hero_query="Kelvin",
        all_heroes=False,
    )

    guide = generated.guides[0]
    policy = generated.policies[0]
    assert policy.schema_version == 5
    assert [card.item_id for card in policy.core_alternatives] == [103]
    optional = next(row for row in guide.categories if row.name == "OPTIONAL CORE")
    assert optional.optional
    assert [item.item_id for item in optional.items] == [103]
    card = policy.core_alternatives[0]
    assert (card.vs, card.why, card.swap) == (
        "Heavy enemy healing",
        "Healing Reduction",
        "Replaces Tier 1 Item 1",
    )
    assert optional.items[0].annotation.startswith("SOUL WINDOW: ")
    assert 103 not in {item.item_id for item in guide.tiers[1]}
    assert all(node.item_id != 103 for node in policy.nodes)
    assert BuildPolicy.from_dict(policy.as_dict()) == policy

    document = build_strategy_context_document(
        generated.patch,
        list(generated.contexts),
        manifest=generated.manifest,
        item_mechanics=generated.item_mechanics,
        requested_hero_ids=set(generated.eligible_hero_ids),
        exclusions=generated.exclusions,
    )
    validate_strategy_context_document(document)
