import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from deadlock_build_sync.ability_order import AbilityPath
from deadlock_build_sync.api import Patch
from deadlock_build_sync.artifacts import build_policy_artifact
from deadlock_build_sync.narratives import (
    NARRATIVE_GENERATOR_VERSION,
    NARRATIVE_SCHEMA_VERSION,
)
from deadlock_build_sync.policy import (
    BuildPolicy,
    ClaimClass,
    EvidenceClaim,
    NodeKind,
    PolicyNode,
)
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
from deadlock_build_sync.value_validation import (
    integer,
    require_object_rows,
)
from tests.artifact_projection_fixtures import _projection
from tests.canonical_bundle_fixtures import canonical_projection, fixture_kit
from tests.discovery_fixtures import current_document

__all__ = ["_projection"]

PATCH = Patch("Patch", 100, "2026-01-01T00:00:00Z")


def _manifest(evidence: dict[str, object], raw_evidence: bytes) -> SnapshotManifest:
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
                    "method": "state-aware-multi-path-v8",
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
    core_ids = tuple(range(1001, 1007))
    nodes = (
        *(
            PolicyNode(
                f"core-{index}",
                NodeKind.PURCHASE,
                next_id=f"core-{index + 1}" if index < 6 else "end",
                item_id=item_id,
                evidence_ref="fixture",
            )
            for index, item_id in enumerate(core_ids, start=1)
        ),
        PolicyNode("end", NodeKind.END),
    )
    ability_plan = tuple(
        PolicyNode(
            f"ability-{index}",
            NodeKind.ABILITY,
            ability_id=ability_id,
            level=index,
            evidence_ref="fixture",
        )
        for index, ability_id in enumerate((10, 20, 30, 40) * 4, start=1)
    )
    return BuildPolicy(
        schema_version=5,
        hero_id=12,
        variant="state-aware-multi-path-v5",
        invariant_kit_id="kit",
        strategic_role="Control committed fights",
        snapshot_id=snapshot_id,
        entry="core-1",
        nodes=nodes,
        evidence=(
            EvidenceClaim(
                "fixture",
                ClaimClass.DESCRIPTIVE,
                snapshot_id,
                {"match_mode": "ranked"},
                EvidenceUnit.ELIGIBLE_APPEARANCE,
                200,
                (),
                frozenset(),
            ),
        ),
        ability_plan=ability_plan,
    )


def _build_evidence() -> dict[str, object]:
    items: list[dict[str, object]] = []
    rows = require_object_rows(_projection()["categories"])
    for row_index, row in enumerate(rows):
        for offset, projected in enumerate(require_object_rows(row["items"])):
            tier = (offset // 2) + 1 if row_index == 0 else row_index
            adopters = 80 - offset
            training_adopters = 40
            validation_adopters = 20
            test_adopters = adopters - training_adopters - validation_adopters
            selection_adopters = training_adopters + validation_adopters
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
                "selection_adopter_matches": selection_adopters,
                "selection_eligible_player_matches": 75,
                "training_adopter_matches": training_adopters,
                "training_eligible_player_matches": 50,
                "validation_adopter_matches": validation_adopters,
                "validation_eligible_player_matches": 25,
                "test_adopter_matches": test_adopters,
                "test_eligible_player_matches": 25,
                "selection_adoption": selection_adopters / 75,
                "training_adoption": training_adopters / 50,
                "validation_adoption": validation_adopters / 25,
                "test_adoption": test_adopters / 25,
                "selection_median_buy_time_s": float(300 + offset),
                "selection_median_valid_buy_net_worth": (q25 + q75) / 2,
                "selection_buy_net_worth_q25": q25,
                "selection_buy_net_worth_q75": q75,
                "selection_valid_buy_net_worth_share": 1.0,
                "selection_valid_buy_net_worth_observations": selection_adopters,
                "training_valid_buy_net_worth_observations": training_adopters,
                "validation_valid_buy_net_worth_observations": validation_adopters,
                "training_buy_net_worth_q25": q25,
                "training_buy_net_worth_q75": q75,
                "validation_buy_net_worth_q25": q25,
                "validation_buy_net_worth_q75": q75,
                "imbue_target_ability_id": None,
                "imbue_target_ability": None,
                "imbue_target_matches": 0,
                "imbue_observations": 0,
                "imbue_target_share": 0.0,
            })
    boundary = EpochBoundary(PATCH.identity, 100)
    payload = {
        "schema_version": 9,
        "producer": "fixture",
        "method": {
            "version": "state-aware-multi-path-v8",
            "minimum_core_item_count": 4,
            "maximum_core_item_count": 9,
            "minimum_core_support": 20,
            "minimum_tier_support": 20,
            "minimum_tier_adoption": 0.05,
            "maximum_tier_adoption_drift": 0.1,
            "tier_item_count": 10,
            "minimum_purchase_window_coverage": 0.5,
            "minimum_purchase_window_observations": 20,
            "minimum_imbue_support": 20,
            "minimum_imbue_share": 0.5,
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
                "selection_eligible_player_matches": 75,
                "fold_eligible_player_matches": {
                    "train": 50,
                    "validation": 25,
                    "test": 25,
                },
                "median_final_net_worth": 38_000,
                "core_policy": {
                    "version": 3,
                    "backbone_item_ids": list(range(1001, 1005)),
                    "default_item_ids": list(range(1001, 1007)),
                    "backbone_matches": 40,
                    "backbone_fold_matches": {
                        "train": 20,
                        "validation": 20,
                        "test": 20,
                    },
                    "default_matches": 50,
                    "default_fold_matches": {
                        "train": 30,
                        "validation": 20,
                        "test": 10,
                    },
                    "alternatives": [],
                    "candidate_audit": [],
                    "evaluation": {"method": "cross-fitted-dr"},
                },
                "items": items,
                "tier_policy": {
                    "version": 1,
                    "item_ids_by_tier": {
                        str(tier): [
                            integer(item["item_id"])
                            for item in require_object_rows(rows[tier]["items"])
                        ]
                        for tier in range(1, 5)
                    },
                },
                "sequence_policy": {
                    "version": 3,
                    "minimum_support": 20,
                    "production_model": "deterministic_backoff",
                    "component_expanded_default_path": list(range(1001, 1007)),
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
                },
                "situational_policy": {
                    "version": 2,
                    "threat_vocabulary": [
                        "active_slot_burden",
                        "ally_protection",
                        "bullet_pressure",
                        "control",
                        "healing",
                        "mobility_denial",
                        "mobility_escape",
                        "spirit_pressure",
                    ],
                    "branches": [],
                    "abstentions": ["No branch passed every gate."],
                },
            }
        ],
    }
    flat_hero = payload["heroes"][0]
    payload["heroes"] = [
        {
            "hero_id": flat_hero["hero_id"],
            "hero": flat_hero["hero"],
            "builds": [
                {
                    "path_id": "default",
                    "path_label": "Evidence Default",
                    "signature_item_ids": [],
                    "discovery": {"method": "single-supported-path"},
                    **{
                        key: value
                        for key, value in flat_hero.items()
                        if key not in {"hero_id", "hero"}
                    },
                }
            ],
        }
    ]
    assets = [
        {
            "id": item["item_id"],
            "name": item["item"],
            "class_name": f"item_{item['item_id']}",
            "cost": item["cost"],
            "item_tier": item["tier"],
            "item_slot_type": item["slot"],
            "shopable": True,
            "is_active_item": item["active"],
            "component_items": [],
        }
        for item in items
    ]
    return current_document(payload, assets)


def _write_bundle(root: Path) -> tuple[Path, Path, Path, Path]:
    evidence = _build_evidence()
    raw_evidence = json.dumps(evidence).encode()
    evidence_path = root / "build-evidence.json"
    evidence_path.write_bytes(raw_evidence)
    manifest = _manifest(evidence, raw_evidence)
    policy = _policy(manifest.snapshot_id)
    categories, cost, guidance = canonical_projection(evidence_path, policy)
    hero: dict[str, object] = {
        "hero_id": 12,
        "path_id": "default",
        "path_label": "Evidence Default",
        "hero": "Kelvin",
        "hero_mechanics": fixture_kit(),
        "item_mechanics_ids": [],
        "item_mechanics_sha256": sha256_json({}),
        "snapshot_id": manifest.snapshot_id,
        "policy_id": policy.policy_id,
        "ability_policy": {
            "selection": "MOST_SUPPORTED_LEGAL_STATE",
            "quality": AbilityPath(
                (10, 20, 30, 40) * 4, 235, 135, 100, 250
            ).quality_assessment(),
            "all_valid_telemetry_appearances": 250,
            "complete_path_appearances": 150,
            "final_branch_support": 100,
            "observed_final_branch_outcome_rate": 0.6,
            "steps": [
                {
                    "ability_id": ability_id,
                    "decision_reached_support": 250 - index,
                }
                for index, ability_id in enumerate((10, 20, 30, 40) * 4)
            ],
        },
        "core": {
            "joint_player_matches": 50,
            "joint_share": 0.1,
            "median_final_net_worth": 38_000,
            "core_target_cost": cost,
        },
        "projection": {**_projection(), "guide_version": 3, "categories": categories},
        "purchase_guidance": guidance,
        "explainable_actions": [
            {
                "node_id": f"core-{index}",
                "action_id": item_id,
                "action": f"Item {item_id}",
                "evidence_ref": f"core-evidence-{index}",
            }
            for index, item_id in enumerate(range(1001, 1007), start=1)
        ],
    }
    hero["kit_basis_sha256"] = calculate_kit_basis_sha256(hero)
    hero["narrative_basis_sha256"] = calculate_narrative_basis_sha256(hero)
    hero["context_sha256"] = calculate_context_sha256(hero)
    context: dict[str, object] = {
        "schema_version": CONTEXT_SCHEMA_VERSION,
        "snapshot_manifest": manifest.as_dict(),
        "patch": PATCH.as_dict(),
        "filters": {"match_mode": "ranked", "game_mode": "normal"},
        "requested_hero_ids": [12],
        "exclusions": [],
        "item_mechanics": {},
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
        "generator_version": NARRATIVE_GENERATOR_VERSION,
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
                "path_id": "default",
                "generator_version": NARRATIVE_GENERATOR_VERSION,
                "snapshot_id": manifest.snapshot_id,
                "policy_id": policy.policy_id,
                "context_sha256": hero["context_sha256"],
                "narrative_basis_sha256": hero["narrative_basis_sha256"],
                "build_description": (
                    "Control committed fights around allied pressure while the "
                    "reviewed CORE path keeps reliable damage available."
                ),
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
