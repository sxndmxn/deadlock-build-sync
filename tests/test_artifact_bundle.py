import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from deadlock_build_sync.api import Patch
from deadlock_build_sync.artifact_bundle import load_artifact_guide_bundle
from deadlock_build_sync.artifacts import build_policy_artifact
from deadlock_build_sync.narratives import (
    NARRATIVE_PROMPT_VERSION,
    NARRATIVE_SCHEMA_VERSION,
)
from deadlock_build_sync.policy import BuildPolicy, NodeKind, PolicyNode
from deadlock_build_sync.ranks import DEFAULT_RANK_RANGE
from deadlock_build_sync.snapshot import (
    EpochBoundary,
    EpochSet,
    EvidenceRecord,
    EvidenceUnit,
    MatchMode,
    OutcomePolicy,
    SnapshotManifest,
    sha256_json,
)
from deadlock_build_sync.strategy_context import (
    CONTEXT_SCHEMA_VERSION,
    calculate_context_sha256,
    calculate_kit_basis_sha256,
    calculate_narrative_basis_sha256,
    calculate_source_context_sha256,
)

PATCH = Patch("Patch", 100, "2026-01-01T00:00:00Z")


def _manifest(evidence: dict[str, Any], raw_evidence: bytes) -> SnapshotManifest:
    boundary = EpochBoundary(PATCH.identity, 100)
    rank_range = DEFAULT_RANK_RANGE.as_dict()
    rank_range["labels_sha256"] = "a" * 64
    return SnapshotManifest(
        client_version=123,
        as_of_timestamp=200,
        created_at=datetime.now(UTC).isoformat(),
        match_mode=MatchMode.RANKED,
        game_mode="normal",
        rank_range=rank_range,
        rank_labels_sha256="a" * 64,
        build_tags_sha256="b" * 64,
        patch=PATCH.as_dict(),
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
                "reject",
            ),
            EvidenceRecord(
                "artifact:build-evidence",
                {
                    "artifact_id": evidence["artifact_id"],
                    "hero_count": 1,
                    "method": "reconstructed-final-inventory-v3",
                },
                datetime.now(UTC).isoformat(),
                hashlib.sha256(raw_evidence).hexdigest(),
                len(raw_evidence),
                EvidenceUnit.ELIGIBLE_APPEARANCE,
                "reconstructed-final-inventory-and-first-ownership",
                "reject; no aggregate-API approximation",
            ),
        ),
    )


def _policy(snapshot_id: str) -> BuildPolicy:
    core_ids = tuple(range(1001, 1009))
    nodes = (
        *(
            PolicyNode(
                f"core-{index}",
                NodeKind.PURCHASE,
                next_id=f"core-{index + 1}" if index < 8 else "end",
                item_id=item_id,
            )
            for index, item_id in enumerate(core_ids, start=1)
        ),
        PolicyNode("end", NodeKind.END),
    )
    ability_ids = (10, 20, 30, 40) * 4
    ability_plan = tuple(
        PolicyNode(
            f"ability-{index}",
            NodeKind.ABILITY,
            ability_id=ability_id,
            level=index,
        )
        for index, ability_id in enumerate(ability_ids, start=1)
    )
    return BuildPolicy(
        schema_version=1,
        hero_id=12,
        variant="coherent-eight-item-core",
        invariant_kit_id="kit",
        strategic_role="Control committed fights",
        snapshot_id=snapshot_id,
        entry="core-1",
        nodes=nodes,
        evidence=(),
        ability_plan=ability_plan,
    )


def _projection() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for row_index, (name, count) in enumerate((
        ("CORE ITEMS", 8),
        ("TIER 1", 10),
        ("TIER 2", 10),
        ("TIER 3", 10),
        ("TIER 4", 10),
    )):
        start = 1001 if row_index == 0 else 2000 + row_index * 100
        rows.append({
            "name": name,
            "optional": row_index > 0,
            "items": [
                {
                    "item_id": start + offset,
                    "item": f"Item {start + offset}",
                    "annotation": f"Observed evidence for item {start + offset}.",
                    "required_flex_slots": None,
                    "sell_priority": None,
                    "imbue_target_ability_id": None,
                }
                for offset in range(count)
            ],
        })
    return {
        "build": {
            "archetype": "Weapon Damage",
            "tag_ids": [1, 2, 3],
            "tag_classes": [
                "citadel_build_tag_weapon",
                "citadel_build_tag_damage",
                "citadel_build_tag_complexity_2",
            ],
            "tag_labels": ["Weapon", "Damage", "For Intermediate Players"],
            "tag_catalog_sha256": "b" * 64,
        },
        "categories": rows,
        "semantics": "CORE only; tiers are optional.",
    }


def _build_evidence() -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for row_index, row in enumerate(_projection()["categories"]):
        for offset, projected in enumerate(row["items"]):
            tier = (offset // 2) + 1 if row_index == 0 else row_index
            adopters = 80 - offset
            wins = adopters // 2
            q25 = float(4_000 * tier + offset * 100)
            q75 = q25 + 10_000
            items.append({
                "item_id": projected["item_id"],
                "item": projected["item"],
                "tier": tier,
                "cost": tier * 800,
                "slot": "weapon",
                "active": False,
                "adopter_matches": adopters,
                "eligible_player_matches": 100,
                "purchase_events": adopters,
                "wins": wins,
                "adoption": adopters / 100,
                "observed_outcome_rate": wins / adopters,
                "median_buy_time_s": float(300 + offset),
                "median_valid_buy_net_worth": (q25 + q75) / 2,
                "buy_net_worth_q25": q25,
                "buy_net_worth_q75": q75,
                "valid_buy_net_worth_share": 0.95,
            })
    boundary = EpochBoundary(PATCH.identity, 100)
    payload = {
        "schema_version": 2,
        "producer": "fixture",
        "method": {
            "version": "reconstructed-final-inventory-v3",
            "core_item_count": 8,
            "core_candidate_limit": 64,
            "minimum_core_support": 20,
            "minimum_tier_support": 20,
            "tier_item_count": 10,
        },
        "cohort": {
            "as_of": datetime.fromtimestamp(200, UTC).isoformat(),
            "match_mode": "Ranked",
            "game_mode": "Normal",
            "minimum_badge": DEFAULT_RANK_RANGE.minimum.badge_id,
            "maximum_badge": DEFAULT_RANK_RANGE.maximum.badge_id,
        },
        "patch": PATCH.as_dict(),
        "epochs": EpochSet(boundary, boundary, boundary, boundary).as_dict(),
        "client_version": 123,
        "rank_labels_sha256": "a" * 64,
        "heroes_sha256": "b" * 64,
        "items_sha256": "c" * 64,
        "requested_hero_ids": [12],
        "heroes": [
            {
                "hero_id": 12,
                "hero": "Kelvin",
                "eligible_player_matches": 100,
                "median_final_net_worth": 38_000,
                "core_candidates": [
                    {
                        "item_ids": list(range(1001, 1009)),
                        "joint_matches": 50,
                    }
                ],
                "items": items,
                "sequence_policy": {
                    "version": 1,
                    "minimum_support": 20,
                    "production_model": "deterministic_backoff",
                    "component_expanded_default_path": list(range(1001, 1009)),
                    "transitions": [
                        {
                            "level": "popularity",
                            "first_item_id": 0,
                            "previous_item_id": 0,
                            "position": 0,
                            "next_item_id": 1001,
                            "support": 50,
                            "context_support": 100,
                        }
                    ],
                    "evaluation": {"chronological_fold": "test"},
                    "challenger": {
                        "evaluated": True,
                        "passed": False,
                        "promoted": False,
                    },
                },
                "situational_policy": {
                    "version": 1,
                    "threat_vocabulary": [
                        "active_slot_burden",
                        "ally_protection",
                        "bullet_pressure",
                        "control",
                        "healing",
                        "mobility_escape",
                        "spirit_pressure",
                    ],
                    "branches": [],
                    "abstentions": ["No branch passed every gate."],
                },
            }
        ],
    }
    return {**payload, "artifact_id": sha256_json(payload)}


def _write_bundle(root: Path) -> tuple[Path, Path, Path, Path]:
    evidence = _build_evidence()
    raw_evidence = json.dumps(evidence).encode()
    evidence_path = root / "build-evidence.json"
    evidence_path.write_bytes(raw_evidence)
    manifest = _manifest(evidence, raw_evidence)
    policy = _policy(manifest.snapshot_id)
    ability_ids = (10, 20, 30, 40) * 4
    hero = {
        "hero_id": 12,
        "hero": "Kelvin",
        "hero_mechanics": {"class_name": "hero_kelvin"},
        "snapshot_id": manifest.snapshot_id,
        "policy_id": policy.policy_id,
        "ability_policy": {
            "selection": "MOST_SUPPORTED_LEGAL_STATE",
            "all_valid_telemetry_appearances": 250,
            "complete_path_appearances": 150,
            "final_branch_support": 100,
            "observed_final_branch_outcome_rate": 0.6,
            "steps": [
                {
                    "ability_id": ability_id,
                    "decision_reached_support": 250 - index,
                }
                for index, ability_id in enumerate(ability_ids)
            ],
        },
        "core": {
            "joint_player_matches": 50,
            "joint_share": 0.1,
            "median_final_net_worth": 38_000,
            "core_target_cost": 27_200,
        },
        "projection": _projection(),
        "explainable_actions": [
            {
                "node_id": f"core-{index}",
                "action_id": item_id,
                "action": f"Item {item_id}",
                "evidence_ref": f"core-evidence-{index}",
            }
            for index, item_id in enumerate(range(1001, 1009), start=1)
        ],
    }
    hero["kit_basis_sha256"] = calculate_kit_basis_sha256(hero)
    hero["narrative_basis_sha256"] = calculate_narrative_basis_sha256(hero)
    hero["context_sha256"] = calculate_context_sha256(hero)
    context = {
        "schema_version": CONTEXT_SCHEMA_VERSION,
        "snapshot_manifest": manifest.as_dict(),
        "patch": PATCH.as_dict(),
        "filters": {"match_mode": "ranked", "game_mode": "normal"},
        "requested_hero_ids": [12],
        "exclusions": [],
        "heroes": [hero],
    }
    context["source_context_sha256"] = calculate_source_context_sha256(context)
    policies = build_policy_artifact(
        [policy],
        snapshot_manifest=manifest.as_dict(),
        requested_hero_ids={12},
    )
    narratives = {
        "schema_version": NARRATIVE_SCHEMA_VERSION,
        "prompt_version": NARRATIVE_PROMPT_VERSION,
        "source_context_sha256": context["source_context_sha256"],
        "snapshot_id": manifest.snapshot_id,
        "patch": PATCH.as_dict(),
        "cohort": {
            "client_version": 123,
            "match_mode": "ranked",
            "game_mode": "normal",
        },
        "requested_hero_ids": [12],
        "exclusions": [],
        "heroes": [
            {
                "hero_id": 12,
                "prompt_version": NARRATIVE_PROMPT_VERSION,
                "snapshot_id": manifest.snapshot_id,
                "policy_id": policy.policy_id,
                "context_sha256": hero["context_sha256"],
                "narrative_basis_sha256": hero["narrative_basis_sha256"],
                "tactical_profile": {
                    "primary_role": "control support",
                    "fight_role": "Control committed fights around allied pressure.",
                    "economy_plan": "Take safe income before grouping for objectives.",
                },
                "build_summary": "Use the reviewed coherent core.",
                "action_explanations": [
                    {
                        "node_id": f"core-{index}",
                        "evidence_ref": f"core-evidence-{index}",
                        "instruction": (
                            f"Use Item {item_id} at its observed place in the core."
                        ),
                    }
                    for index, item_id in enumerate(range(1001, 1009), start=1)
                ],
                "category_summaries": [
                    {"category": name, "summary": f"Reviewed summary for {name}."}
                    for name in ("CORE ITEMS", "TIER 1", "TIER 2", "TIER 3", "TIER 4")
                ],
            }
        ],
    }
    context_path = root / "strategy-context.json"
    policy_path = root / "policies.json"
    narrative_path = root / "narratives.json"
    context_path.write_text(json.dumps(context), encoding="utf-8")
    policy_path.write_text(json.dumps(policies), encoding="utf-8")
    narrative_path.write_text(json.dumps(narratives), encoding="utf-8")
    return context_path, policy_path, narrative_path, evidence_path


def test_loads_exact_reviewed_bundle_without_analytics_refetch(tmp_path: Path) -> None:
    context_path, policy_path, narrative_path, evidence_path = _write_bundle(tmp_path)

    bundle = load_artifact_guide_bundle(
        context_path,
        policy_path,
        narrative_path,
        evidence_path,
    )

    assert len(bundle.guides) == 1
    guide = bundle.guides[0]
    assert guide.hero_name == "Kelvin"
    assert guide.item_count == 48
    assert [len(category.items) for category in guide.rendered_categories] == [
        8,
        10,
        10,
        10,
        10,
    ]
    assert guide.summary == "Use the reviewed coherent core."
    assert guide.rendered_categories[0].description == (
        "AUTO QUEUE • Default path, buy left→right."
    )
    assert guide.rendered_categories[1].description == (
        "OPTIONAL • Excluded from Queue; choose deliberately."
    )
    assert guide.rendered_categories[0].items[0].annotation == (
        "Use Item 1001 at its observed place in the core.\n"
        "Usually 4k–14k souls • adopted 80.0% (n=100)"
    )
    assert guide.ability_path is not None
    assert len(guide.ability_path.ability_ids) == 16


def test_rejects_edited_projection_even_when_other_artifacts_are_unchanged(
    tmp_path: Path,
) -> None:
    context_path, policy_path, narrative_path, evidence_path = _write_bundle(tmp_path)
    context = json.loads(context_path.read_text(encoding="utf-8"))
    context["heroes"][0]["projection"]["categories"][0]["items"][0]["item_id"] = 999
    context_path.write_text(json.dumps(context), encoding="utf-8")

    with pytest.raises(ValueError, match="edited"):
        load_artifact_guide_bundle(
            context_path,
            policy_path,
            narrative_path,
            evidence_path,
        )


def test_rejects_crossed_policy_snapshot(tmp_path: Path) -> None:
    context_path, policy_path, narrative_path, evidence_path = _write_bundle(tmp_path)
    policies = json.loads(policy_path.read_text(encoding="utf-8"))
    policies["snapshot_manifest"]["created_at"] = "2026-02-01T00:00:00Z"
    policy_path.write_text(json.dumps(policies), encoding="utf-8")

    with pytest.raises(ValueError, match="manifests differ"):
        load_artifact_guide_bundle(
            context_path,
            policy_path,
            narrative_path,
            evidence_path,
        )


def test_rejects_build_evidence_outside_the_reviewed_snapshot(tmp_path: Path) -> None:
    context_path, policy_path, narrative_path, evidence_path = _write_bundle(tmp_path)
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["producer"] = "other-fixture"
    payload = {key: value for key, value in evidence.items() if key != "artifact_id"}
    evidence["artifact_id"] = sha256_json(payload)
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")

    with pytest.raises(ValueError, match="differs from the artifact snapshot"):
        load_artifact_guide_bundle(
            context_path,
            policy_path,
            narrative_path,
            evidence_path,
        )
