from __future__ import annotations

import json
import math
from typing import TYPE_CHECKING

from deadlock_build_sync.mechanics import ItemGraph
from deadlock_build_sync.ranks import RankCatalog
from deadlock_build_sync.snapshot import (
    EpochBoundary,
    EpochSet,
    sha256_json,
)
from deadlock_build_sync.value_validation import (
    integer,
    number,
    require_object_dict,
    require_object_rows,
)

if TYPE_CHECKING:
    from pathlib import Path

from tests.discovery_fixtures import current_document

PATCH_IDENTITY = "f" * 64


def _assets() -> list[dict[str, object]]:
    return [
        {
            "id": tier * 100 + index,
            "name": f"Tier {tier} Item {index}",
            "class_name": f"item_t{tier}_{index}",
            "item_tier": tier,
            "cost": tier * 1_000,
            "item_slot_type": "weapon",
            "shopable": True,
            "disabled": False,
            "is_active_item": False,
            "is_unique": True,
            "component_items": [],
        }
        for tier in range(1, 5)
        for index in range(1, 12)
    ]


def _epochs(identity: str = PATCH_IDENTITY) -> EpochSet:
    boundary = EpochBoundary(identity, 1_700_000_000)
    return EpochSet(boundary, boundary, boundary, boundary)


def _rank_catalog() -> RankCatalog:
    return RankCatalog({tier: f"Rank {tier}" for tier in range(1, 12)})


def _item(asset: dict[str, object], *, eligible: int = 1_000) -> dict[str, object]:
    item_id = integer(asset["id"])
    index = item_id % 100
    adopters = 200 - index
    wins = adopters if index == 11 else adopters // 2
    median_net_worth = None if index == 10 else float(item_id * 10)
    training_adopters = round(adopters * 0.6)
    validation_adopters = round(adopters * 0.2)
    test_adopters = adopters - training_adopters - validation_adopters
    selection_adopters = training_adopters + validation_adopters
    return {
        "item_id": item_id,
        "item": asset["name"],
        "tier": asset["item_tier"],
        "cost": asset["cost"],
        "slot": asset["item_slot_type"],
        "active": asset["is_active_item"],
        "adopter_matches": adopters,
        "eligible_player_matches": eligible,
        "purchase_events": adopters + 10,
        "wins": wins,
        "adoption": adopters / eligible,
        "observed_outcome_rate": wins / adopters,
        "median_buy_time_s": float(10_000 - item_id),
        "median_valid_buy_net_worth": median_net_worth,
        "buy_net_worth_q25": median_net_worth,
        "buy_net_worth_q75": median_net_worth,
        "valid_buy_net_worth_share": 0.9,
        "selection_adopter_matches": selection_adopters,
        "selection_eligible_player_matches": 800,
        "training_adopter_matches": training_adopters,
        "training_eligible_player_matches": 600,
        "validation_adopter_matches": validation_adopters,
        "validation_eligible_player_matches": 200,
        "test_adopter_matches": test_adopters,
        "test_eligible_player_matches": 200,
        "selection_adoption": selection_adopters / 800,
        "training_adoption": training_adopters / 600,
        "validation_adoption": validation_adopters / 200,
        "test_adoption": test_adopters / 200,
        "selection_median_buy_time_s": float(10_000 - item_id),
        "selection_median_valid_buy_net_worth": median_net_worth,
        "selection_buy_net_worth_q25": median_net_worth,
        "selection_buy_net_worth_q75": median_net_worth,
        "selection_valid_buy_net_worth_share": (
            0.0 if median_net_worth is None else 1.0
        ),
        "selection_valid_buy_net_worth_observations": (
            0 if median_net_worth is None else selection_adopters
        ),
        "training_valid_buy_net_worth_observations": (
            0 if median_net_worth is None else training_adopters
        ),
        "validation_valid_buy_net_worth_observations": (
            0 if median_net_worth is None else validation_adopters
        ),
        "training_buy_net_worth_q25": median_net_worth,
        "training_buy_net_worth_q75": median_net_worth,
        "validation_buy_net_worth_q25": median_net_worth,
        "validation_buy_net_worth_q75": median_net_worth,
        "imbue_target_ability_id": None,
        "imbue_target_ability": None,
        "imbue_target_matches": 0,
        "imbue_observations": 0,
        "imbue_target_share": 0.0,
    }


def _has_visible_fixture_upgrade(
    item_id: int,
    tier: int,
    graph: ItemGraph,
    visible_higher_tier_ids: set[int],
) -> bool:
    upgrades_by_tier = {
        child_tier: {
            child_id
            for child_id in graph.children[item_id]
            if graph.nodes[child_id].tier == child_tier
        }
        for child_tier in range(tier + 1, 5)
    }
    return all(
        not child_ids or bool(child_ids & visible_higher_tier_ids)
        for child_ids in upgrades_by_tier.values()
    )


def _fixture_tier_items(
    tier: int,
    item_rows: list[dict[str, object]],
    graph: ItemGraph,
    excluded_ids: set[int],
    visible_higher_tier_ids: set[int],
) -> list[int]:
    qualified = []
    for item in item_rows:
        item_id = integer(item["item_id"])
        if integer(item["tier"]) != tier or item_id in excluded_ids:
            continue
        if _has_visible_fixture_upgrade(item_id, tier, graph, visible_higher_tier_ids):
            qualified.append(item)
    selected = sorted(
        qualified,
        key=lambda item: (
            -number(item["training_adoption"]),
            -integer(item["training_adopter_matches"]),
            integer(item["item_id"]),
        ),
    )[:10]
    selected = sorted(
        selected,
        key=lambda item: (
            item["selection_median_valid_buy_net_worth"] is None,
            number(item["selection_median_valid_buy_net_worth"] or float("inf")),
            number(item["selection_median_buy_time_s"] or float("inf")),
            integer(item["item_id"]),
        ),
    )
    return [integer(item["item_id"]) for item in selected]


def _fixture_tier_membership(
    item_rows: list[dict[str, object]],
    graph: ItemGraph,
    excluded_ids: set[int],
) -> dict[str, list[int]]:
    visible_higher_tier_ids: set[int] = set()
    membership: dict[str, list[int]] = {}
    for tier in range(4, 0, -1):
        selected_ids = _fixture_tier_items(
            tier,
            item_rows,
            graph,
            excluded_ids,
            visible_higher_tier_ids,
        )
        membership[str(tier)] = selected_ids
        visible_higher_tier_ids.update(selected_ids)
    return membership


def _document(
    *,
    assets: list[dict[str, object]] | None = None,
    median_final_net_worth: int = 30_000,
    default_item_ids: list[int] | None = None,
    core_alternatives: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    current_assets = assets or _assets()
    item_rows = [_item(asset) for asset in current_assets]
    selected_default = default_item_ids or [101, 102, 201, 202, 301, 302]
    optional_ids = {integer(row["item_id"]) for row in (core_alternatives or [])}
    graph = ItemGraph.from_assets(current_assets)
    tier_membership = _fixture_tier_membership(
        item_rows, graph, set(selected_default) | optional_ids
    )
    heroes = [{"id": 13, "name": "Haze"}]
    sequence_policy = {
        "version": 3,
        "minimum_support": 20,
        "production_model": "deterministic_backoff",
        "component_expanded_default_path": list(selected_default),
        "transitions": [
            {
                "level": "popularity",
                "first_item_id": 0,
                "previous_item_id": 0,
                "position": 0,
                "next_item_id": 101,
                "support": 50,
                "context_support": 100,
            }
        ],
        "evaluation": {"chronological_fold": "test"},
    }
    payload = {
        "schema_version": 9,
        "producer": "deadlock-build-sync.offline",
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
            "as_of": "2026-08-09T00:00:00+00:00",
            "match_mode": "Ranked",
            "game_mode": "Normal",
            "minimum_badge": 71,
            "maximum_badge": 115,
        },
        "patch": {"identity": PATCH_IDENTITY},
        "epochs": _epochs().as_dict(),
        "client_version": 6_673,
        "rank_labels_sha256": _rank_catalog().sha256,
        "heroes_sha256": sha256_json(heroes),
        "items_sha256": sha256_json(current_assets),
        "requested_hero_ids": [13],
        "heroes": [
            {
                "hero_id": 13,
                "hero": "Haze",
                "builds": [
                    {
                        "path_id": "default",
                        "path_label": "Evidence Default",
                        "signature_item_ids": [],
                        "discovery": {"method": "single-supported-path"},
                        "eligible_player_matches": 1_000,
                        "selection_eligible_player_matches": 800,
                        "fold_eligible_player_matches": {
                            "train": 600,
                            "validation": 200,
                            "test": 200,
                        },
                        "median_final_net_worth": median_final_net_worth,
                        "core_policy": {
                            "version": 3,
                            "backbone_item_ids": [101, 102, 201, 202],
                            "default_item_ids": selected_default,
                            "backbone_matches": 60,
                            "backbone_fold_matches": {
                                "train": 30,
                                "validation": 30,
                                "test": 30,
                            },
                            "default_matches": 80,
                            "default_fold_matches": {
                                "train": 40,
                                "validation": 40,
                                "test": 20,
                            },
                            "alternatives": core_alternatives or [],
                            "candidate_audit": [],
                            "evaluation": {"method": "cross-fitted-dr"},
                        },
                        "items": item_rows,
                        "tier_policy": {
                            "version": 1,
                            "item_ids_by_tier": tier_membership,
                        },
                        "sequence_policy": sequence_policy,
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
        ],
    }
    return current_document(payload, current_assets)


def _write(path: Path, document: dict[str, object]) -> None:
    path.write_text(json.dumps(document), encoding="utf-8")


def _refingerprint(document: dict[str, object]) -> None:
    document.pop("artifact_id", None)
    document["artifact_id"] = sha256_json(document)


def write_fingerprinted_evidence(path: Path, document: dict[str, object]) -> None:
    """Write an edited fixture with a matching fingerprint for validation tests."""
    _refingerprint(document)
    _write(path, document)


def _first_build(document: dict[str, object]) -> dict[str, object]:
    heroes = require_object_rows(document["heroes"])
    return require_object_rows(heroes[0]["builds"])[0]


def _first_item(document: dict[str, object]) -> dict[str, object]:
    return require_object_rows(_first_build(document)["items"])[0]


def _sequence_policy(document: dict[str, object]) -> dict[str, object]:
    return require_object_dict(_first_build(document)["sequence_policy"])


def _situational_policy(document: dict[str, object]) -> dict[str, object]:
    return require_object_dict(_first_build(document)["situational_policy"])


def _fixture_card(tier: int, offset: int) -> str:
    """Build the item card the projection must carry for a fixture item.

    Returns:
        The two-line card derived from the values the evidence fixture writes.

    """
    adopters = 80 - offset
    lower = math.floor((4_000 * tier + offset * 100) / 1000 + 0.5)
    return (
        f"SOUL WINDOW: {lower}k - {lower + 10}k\n"
        f"PR: 80.0% | WR: {(adopters // 2) / adopters * 100:.1f}% "
        f"| TOTAL GAMES: 60"
    )
