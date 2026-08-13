from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

import pytest

from deadlock_build_sync.ability_order import AbilityPath
from deadlock_build_sync.api import Patch
from deadlock_build_sync.mechanics import AbilityTimelineStep
from deadlock_build_sync.purchase_guide import GuideItem, PurchaseGuide, PurchaseWindow
from deadlock_build_sync.ranks import DEFAULT_RANK_RANGE
from deadlock_build_sync.snapshot import (
    EpochBoundary,
    EpochSet,
    EvidenceRecord,
    EvidenceUnit,
    MatchMode,
    OutcomePolicy,
    SnapshotManifest,
)
from deadlock_build_sync.strategy_context import (
    CONTEXT_SCHEMA_VERSION,
    StrategyContextError,
    build_hero_strategy_context,
    build_strategy_context_document,
    calculate_context_sha256,
    calculate_kit_basis_sha256,
    calculate_narrative_basis_sha256,
    calculate_source_context_sha256,
    validate_strategy_context_document,
)

SNAPSHOT = "1" * 64
POLICY = "2" * 64


def manifest() -> SnapshotManifest:
    boundary = EpochBoundary("patch", 100)
    return SnapshotManifest(
        client_version=123,
        as_of_timestamp=200,
        created_at=datetime.now(UTC).isoformat(),
        match_mode=MatchMode.RANKED,
        game_mode="normal",
        rank_range=DEFAULT_RANK_RANGE.as_dict(),
        rank_labels_sha256="ranks",
        patch={"identity": "patch"},
        epochs=EpochSet(boundary, boundary, boundary, boundary),
        outcome_policy=OutcomePolicy(),
        outcome_policy_enforced=False,
        records=(
            EvidenceRecord(
                "fixture",
                {},
                datetime.now(UTC).isoformat(),
                "0" * 64,
                1,
                EvidenceUnit.ASSET,
                "fixture",
                "none",
            ),
        ),
    )


def kit() -> dict[str, Any]:
    return {
        "hero_id": 12,
        "description": {
            "summary": "Controls space with ice.",
            "role": "Protect allies.",
            "playstyle": "Control committed fights.",
        },
        "abilities": [
            {
                "id": ability_id,
                "name": name,
                "description": {"desc": f"{name} description."},
                "properties": [],
            }
            for ability_id, name in (
                (10, "Grenade"),
                (20, "Beam"),
                (30, "Path"),
                (40, "Shelter"),
            )
        ],
        "level_info": {},
        "mechanics_sha256": "a" * 64,
    }


def assets() -> list[dict[str, Any]]:
    return [
        {
            "id": ability_id,
            "name": name,
            "class_name": f"ability_{ability_id}",
            "type": "ability",
        }
        for ability_id, name in (
            (10, "Grenade"),
            (20, "Beam"),
            (30, "Path"),
            (40, "Shelter"),
        )
    ] + [
        {
            "id": 101,
            "name": "Rapid Recharge",
            "item_slot_type": "spirit",
            "description": {"passive": "Adds another ability charge."},
            "properties": {"TechPower": {"value": 9, "label": "Spirit Power"}},
        }
    ]


def guide(item: GuideItem) -> PurchaseGuide:
    path = AbilityPath(
        (10, 20, 30, 40),
        100,
        60,
        40,
        250,
        complete_path_matches=100,
        decision_support=(250, 220, 180, 100),
    )
    return PurchaseGuide(
        12,
        "Kelvin",
        "hero_kelvin",
        {1: (item,), 2: (), 3: (), 4: ()},
        ability_path=path,
        snapshot_id=SNAPSHOT,
        policy_id=POLICY,
        client_version=123,
        match_mode="ranked",
        rank_identity="Mystic–Emissary",
    )


def timeline() -> tuple[AbilityTimelineStep, ...]:
    return tuple(
        AbilityTimelineStep(level, ability_id, 1, 1, "unlock", 0, 4 - level)
        for level, ability_id in enumerate((10, 20, 30, 40), start=1)
    )


def item(matches: int = 200) -> GuideItem:
    return GuideItem(
        101,
        "Rapid Recharge",
        1,
        matches,
        0.55,
        0.48,
        1.0,
        (PurchaseWindow(5000, 10000, matches // 2, matches // 4, 0.5, 0.4),),
    )


def test_exports_structured_mechanics_and_real_ability_timeline() -> None:
    context = build_hero_strategy_context(
        guide(item()),
        {"id": 12, "name": "Kelvin"},
        assets(),
        kit=kit(),
        ability_timeline=timeline(),
    )

    assert context["hero_description"]["role"] == "Protect allies."
    assert context["abilities"][0]["name"] == "Grenade"
    assert context["tiers"]["I"][0]["slot"] == "SPIRIT"
    assert context["tiers"]["I"][0]["unit"] == "purchase_event"
    assert (
        context["tiers"]["I"][0]["observed_purchase_event_net_worth_ranges"][0]["label"]
        == "5–10k"
    )
    first_step = context["ability_policy"]["steps"][0]
    assert first_step["earliest_legal_level"] == 1
    assert first_step["decision_reached_support"] == 250
    assert "quarter" not in first_step
    assert context["projection"]["categories"][0]["items"][0]["item_id"] == 101
    assert set(context["fingerprints"]) == {
        "mechanics",
        "analytics",
        "policy_basis",
        "narrative",
        "projection",
    }
    assert context["kit_basis_sha256"] == calculate_kit_basis_sha256(context)
    assert context["narrative_basis_sha256"] == calculate_narrative_basis_sha256(
        context
    )
    assert context["context_sha256"] == calculate_context_sha256(context)


def test_document_binds_snapshot_coverage_and_fingerprints() -> None:
    live_manifest = manifest()
    context = build_hero_strategy_context(
        guide(item()),
        {"id": 12, "name": "Kelvin"},
        assets(),
        kit=kit(),
        ability_timeline=timeline(),
    )
    context["snapshot_id"] = live_manifest.snapshot_id
    context["kit_basis_sha256"] = calculate_kit_basis_sha256(context)
    context["narrative_basis_sha256"] = calculate_narrative_basis_sha256(context)
    context["context_sha256"] = calculate_context_sha256(context)
    document = build_strategy_context_document(
        Patch("Patch", 123, "2026-01-01T00:00:00Z"),
        [context],
        manifest=live_manifest,
        requested_hero_ids={12, 13},
        exclusions=((13, "incomplete mechanics"),),
    )

    assert document["schema_version"] == CONTEXT_SCHEMA_VERSION
    assert document["filters"]["match_mode"] == "ranked"
    assert document["exclusions"] == [{"hero_id": 13, "reason": "incomplete mechanics"}]
    assert document["source_context_sha256"] == calculate_source_context_sha256(
        document
    )
    validate_strategy_context_document(document)

    edited = deepcopy(document)
    edited["heroes"][0]["hero_description"]["role"] = "Edited"
    with pytest.raises(StrategyContextError, match="kit basis was edited"):
        validate_strategy_context_document(edited)


def test_narrative_basis_changes_when_claim_bearing_analytics_change() -> None:
    original = build_hero_strategy_context(
        guide(item(200)),
        {"id": 12, "name": "Kelvin"},
        assets(),
        kit=kit(),
        ability_timeline=timeline(),
    )
    advanced = build_hero_strategy_context(
        guide(item(400)),
        {"id": 12, "name": "Kelvin"},
        assets(),
        kit=kit(),
        ability_timeline=timeline(),
    )

    assert original["kit_basis_sha256"] == advanced["kit_basis_sha256"]
    assert original["narrative_basis_sha256"] != advanced["narrative_basis_sha256"]
    assert original["context_sha256"] != advanced["context_sha256"]


def test_document_rejects_unaccounted_requested_hero() -> None:
    live_manifest = manifest()
    context = build_hero_strategy_context(
        guide(item()),
        {"id": 12, "name": "Kelvin"},
        assets(),
        kit=kit(),
        ability_timeline=timeline(),
    )
    context["snapshot_id"] = live_manifest.snapshot_id
    context["kit_basis_sha256"] = calculate_kit_basis_sha256(context)
    context["narrative_basis_sha256"] = calculate_narrative_basis_sha256(context)
    context["context_sha256"] = calculate_context_sha256(context)

    with pytest.raises(StrategyContextError, match="cover requested heroes"):
        build_strategy_context_document(
            Patch("Patch", 123, "2026-01-01T00:00:00Z"),
            [context],
            manifest=live_manifest,
            requested_hero_ids={12, 13},
        )
