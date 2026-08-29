from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import pytest

from deadlock_build_sync.artifacts import ArtifactError
from deadlock_build_sync.build_evidence import (
    assert_build_evidence_compatible,
    load_build_evidence,
    nondecreasing_window_schedule,
    reliable_purchase_window,
    select_hero_build,
)
from deadlock_build_sync.mechanics import ItemGraph
from deadlock_build_sync.ranks import DEFAULT_RANK_RANGE, RankCatalog
from deadlock_build_sync.snapshot import (
    EpochBoundary,
    EpochSet,
    MatchMode,
    sha256_json,
)

if TYPE_CHECKING:
    from pathlib import Path

PATCH_IDENTITY = "f" * 64


def _assets() -> list[dict[str, Any]]:
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


def _item(asset: dict[str, Any], *, eligible: int = 1_000) -> dict[str, Any]:
    item_id = int(asset["id"])
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


def _document(
    *,
    assets: list[dict[str, Any]] | None = None,
    candidates: list[dict[str, Any]] | None = None,
    median_final_net_worth: int = 30_000,
    default_item_ids: list[int] | None = None,
    core_alternatives: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    del candidates
    current_assets = assets or _assets()
    item_rows = [_item(asset) for asset in current_assets]
    selected_default = default_item_ids or [101, 102, 201, 202, 301, 302, 401, 402]
    optional_ids = {int(row["item_id"]) for row in (core_alternatives or [])}
    graph = ItemGraph.from_assets(current_assets)
    visible_higher_tier_ids: set[int] = set()
    tier_membership: dict[str, list[int]] = {}
    for tier in range(4, 0, -1):
        qualified = []
        for item in item_rows:
            item_id = int(item["item_id"])
            if (
                int(item["tier"]) != tier
                or item_id in selected_default
                or item_id in optional_ids
            ):
                continue
            upgrades_by_tier = {
                child_tier: {
                    child_id
                    for child_id in graph.children[item_id]
                    if graph.nodes[child_id].tier == child_tier
                }
                for child_tier in range(tier + 1, 5)
            }
            if all(
                not child_ids or bool(child_ids & visible_higher_tier_ids)
                for child_ids in upgrades_by_tier.values()
            ):
                qualified.append(item)
        selected = sorted(
            qualified,
            key=lambda item: (
                -float(item["training_adoption"]),
                -int(item["training_adopter_matches"]),
                int(item["item_id"]),
            ),
        )[:10]
        selected = sorted(
            selected,
            key=lambda item: (
                item["selection_median_valid_buy_net_worth"] is None,
                float(item["selection_median_valid_buy_net_worth"] or float("inf")),
                float(item["selection_median_buy_time_s"] or float("inf")),
                int(item["item_id"]),
            ),
        )
        tier_membership[str(tier)] = [int(item["item_id"]) for item in selected]
        visible_higher_tier_ids.update(tier_membership[str(tier)])
    heroes = [{"id": 13, "name": "Haze"}]
    sequence_policy = {
        "version": 3,
        "minimum_support": 20,
        "production_model": "deterministic_backoff",
        "component_expanded_default_path": [101, 102, 201, 202, 301, 302, 401, 402],
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
        "schema_version": 8,
        "producer": "deadlock-build-sync.offline",
        "method": {
            "version": "state-aware-multi-path-v7",
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
    return {**payload, "artifact_id": sha256_json(payload)}


def _write(path: Path, document: dict[str, Any]) -> None:
    path.write_text(json.dumps(document), encoding="utf-8")


def _refingerprint(document: dict[str, Any]) -> None:
    document.pop("artifact_id", None)
    document["artifact_id"] = sha256_json(document)


def test_rejects_previous_build_evidence_schema(tmp_path: Path) -> None:
    path = tmp_path / "build-evidence.json"
    document = _document()
    document["schema_version"] = 6
    _refingerprint(document)
    _write(path, document)

    with pytest.raises(ArtifactError, match="unsupported build-evidence schema"):
        load_build_evidence(path)


def test_purchase_window_requires_fold_support_and_overlap(tmp_path: Path) -> None:
    path = tmp_path / "build-evidence.json"
    _write(path, _document())
    item = load_build_evidence(path).heroes[13].items[0]

    assert reliable_purchase_window(item) == (
        item.selection_buy_net_worth_q25,
        item.selection_buy_net_worth_q75,
    )
    assert (
        reliable_purchase_window(
            replace(item, validation_valid_buy_net_worth_observations=19)
        )
        is None
    )
    assert (
        reliable_purchase_window(
            replace(
                item,
                validation_buy_net_worth_q25=20_000,
                validation_buy_net_worth_q75=22_000,
            )
        )
        is None
    )


def test_unavailable_purchase_window_does_not_constrain_route() -> None:
    assert nondecreasing_window_schedule(
        (1, 2, 3),
        {1: (100.0, 200.0), 3: (150.0, 300.0)},
    ) == (100.0, 100.0, 150.0)


def test_load_and_select_exact_build_layout(tmp_path: Path) -> None:
    path = tmp_path / "build-evidence.json"
    _write(path, _document())

    catalog = load_build_evidence(path)
    selected = select_hero_build(catalog.heroes[13], _assets())

    assert [item.item_id for item in selected.core] == [
        101,
        102,
        201,
        202,
        301,
        302,
        401,
        402,
    ]
    assert selected.core_joint_matches == 80
    assert selected.core_joint_share == 0.10
    assert selected.core_target_cost == 20_000
    assert {tier: len(items) for tier, items in selected.tiers.items()} == {
        1: 9,
        2: 9,
        3: 9,
        4: 9,
    }
    assert [item.item_id for item in selected.tiers[1]] == [
        103,
        104,
        105,
        106,
        107,
        108,
        109,
        111,
        110,
    ]
    assert not {item.item_id for item in selected.core} & {
        item.item_id for items in selected.tiers.values() for item in items
    }
    assert (
        next(
            item for item in catalog.heroes[13].items if item.item_id == 111
        ).observed_outcome_rate
        == 1.0
    )


def test_loads_supported_observed_imbue_target(tmp_path: Path) -> None:
    document = _document()
    item = document["heroes"][0]["builds"][0]["items"][0]
    item.update({
        "imbue_target_ability_id": 40,
        "imbue_target_ability": "Bullet Dance",
        "imbue_target_matches": 75,
        "imbue_observations": 100,
        "imbue_target_share": 0.75,
    })
    _refingerprint(document)
    path = tmp_path / "build-evidence.json"
    _write(path, document)

    loaded = load_build_evidence(path).heroes[13].items[0]

    assert loaded.imbue_target_ability_id == 40
    assert loaded.imbue_target_ability == "Bullet Dance"
    assert loaded.imbue_target_share == 0.75


def test_selection_rejects_policy_core_above_median_final_net_worth(
    tmp_path: Path,
) -> None:
    path = tmp_path / "build-evidence.json"
    candidates = [
        {"item_ids": list(range(403, 411)), "joint_matches": 90},
        {"item_ids": list(range(101, 109)), "joint_matches": 80},
    ]
    _write(path, _document(candidates=candidates, median_final_net_worth=10_000))

    catalog = load_build_evidence(path)
    hero = catalog.heroes[13]
    assets = _assets()
    with pytest.raises(ArtifactError, match="exceeds cohort wealth"):
        select_hero_build(hero, assets)


def test_sparse_supported_tiers_do_not_require_filler(tmp_path: Path) -> None:
    path = tmp_path / "build-evidence.json"
    sparse_assets = [asset for asset in _assets() if int(asset["id"]) % 100 <= 3]
    document = _document(assets=sparse_assets)
    _write(path, document)

    selected = select_hero_build(load_build_evidence(path).heroes[13], _assets())

    assert {tier: len(items) for tier, items in selected.tiers.items()} == {
        1: 1,
        2: 1,
        3: 1,
        4: 1,
    }


def test_optional_component_requires_its_upgrade_in_a_higher_tier_menu(
    tmp_path: Path,
) -> None:
    path = tmp_path / "build-evidence.json"
    assets = _assets()
    next(asset for asset in assets if asset["id"] == 203)["component_items"] = [
        "item_t1_4"
    ]
    next(asset for asset in assets if asset["id"] == 303)["component_items"] = [
        "item_t1_3"
    ]
    assets.extend([
        {
            **assets[11],
            "id": item_id,
            "name": f"Tier 2 Item {item_id % 100}",
            "class_name": f"item_t2_{item_id % 100}",
            "component_items": ["item_t1_3"] if item_id == 213 else [],
        }
        for item_id in (212, 213)
    ])
    _write(path, _document(assets=assets))

    selected = select_hero_build(load_build_evidence(path).heroes[13], assets)

    tier_1_ids = {item.item_id for item in selected.tiers[1]}
    tier_2_ids = {item.item_id for item in selected.tiers[2]}
    assert 203 in tier_2_ids
    assert 104 in tier_1_ids
    assert 213 not in tier_2_ids
    assert 103 not in tier_1_ids


def test_admitted_core_alternative_moves_out_of_its_tier_row(
    tmp_path: Path,
) -> None:
    path = tmp_path / "build-evidence.json"
    alternative = {
        "item_id": 303,
        "comparator_item_id": 302,
        "stage": 6,
        "support": 40,
        "comparison_support": 50,
        "effective_support": 30.0,
        "overlap": 0.8,
        "stable": True,
        "dr_estimate": 0.03,
        "comparative_interval": [0.01, 0.05],
        "vs": "Heavy Spirit damage",
        "why": "Spirit Resist",
        "swap": "Replaces Tier 3 Item 2",
        "when": "Before the next Spirit-heavy fight",
        "skip": "Keep default when control matters more",
        "mechanics_refs": ["asset:item:303:description"],
        "comparator_mechanics_refs": ["asset:item:302:description"],
        "fold_estimates": {
            "train": 0.03,
            "validation": 0.04,
            "test": -0.03,
        },
        "fold_diagnostics": {
            fold: {
                "support": 40,
                "comparison_support": 50,
                "effective_support": 30.0,
                "overlap": 0.8,
                "maximum_standardized_mean_difference": 0.05,
                "estimate": estimate,
                "interval": [0.01, 0.05],
            }
            for fold, estimate in (("train", 0.03), ("validation", 0.04))
        },
    }
    _write(path, _document(core_alternatives=[alternative]))

    selected = select_hero_build(load_build_evidence(path).heroes[13], _assets())

    assert [item.item_id for item in selected.optional_core] == [303]
    assert 303 not in {
        item.item_id for tier_items in selected.tiers.values() for item in tier_items
    }


def test_loader_rejects_tampering(tmp_path: Path) -> None:
    path = tmp_path / "build-evidence.json"
    document = _document()
    document["heroes"][0]["builds"][0]["items"][0]["wins"] = 999
    _write(path, document)

    with pytest.raises(ArtifactError, match="fingerprint"):
        load_build_evidence(path)


def test_loader_rejects_duplicate_permitting_sequence_policy(tmp_path: Path) -> None:
    path = tmp_path / "build-evidence.json"
    document = _document()
    document["heroes"][0]["builds"][0]["sequence_policy"]["version"] = 2
    _refingerprint(document)
    _write(path, document)

    with pytest.raises(ArtifactError, match="sequence policy"):
        load_build_evidence(path)


def test_loader_rejects_repeated_default_path_item(tmp_path: Path) -> None:
    path = tmp_path / "build-evidence.json"
    document = _document()
    document["heroes"][0]["builds"][0]["sequence_policy"][
        "component_expanded_default_path"
    ][1] = 101
    _refingerprint(document)
    _write(path, document)

    with pytest.raises(ArtifactError, match="repeats an item"):
        load_build_evidence(path)


def test_selection_rejects_default_path_outside_soul_windows(tmp_path: Path) -> None:
    path = tmp_path / "build-evidence.json"
    document = _document()
    document["heroes"][0]["builds"][0]["sequence_policy"][
        "component_expanded_default_path"
    ] = [
        102,
        201,
        202,
        301,
        302,
        401,
        402,
        101,
    ]
    _refingerprint(document)
    _write(path, document)

    catalog = load_build_evidence(path)
    hero = catalog.heroes[13]
    assets = _assets()
    with pytest.raises(ArtifactError, match="first-ownership soul windows"):
        select_hero_build(hero, assets)


def test_compatibility_rejects_identity_drift(tmp_path: Path) -> None:
    path = tmp_path / "build-evidence.json"
    heroes = [{"id": 13, "name": "Haze"}]
    _write(path, _document())
    catalog = load_build_evidence(path)
    rank_catalog = _rank_catalog()
    assets = _assets()
    epochs = _epochs()

    with pytest.raises(ArtifactError, match="patch"):
        assert_build_evidence_compatible(
            catalog,
            patch_identity="new-patch",
            client_version=6_673,
            as_of_timestamp=catalog.as_of_timestamp,
            match_mode=MatchMode.RANKED,
            rank_range=DEFAULT_RANK_RANGE,
            rank_catalog=rank_catalog,
            heroes=heroes,
            assets=assets,
            epochs=epochs,
        )

    assert_build_evidence_compatible(
        catalog,
        patch_identity=PATCH_IDENTITY,
        client_version=6_673,
        as_of_timestamp=catalog.as_of_timestamp,
        match_mode=MatchMode.RANKED,
        rank_range=DEFAULT_RANK_RANGE,
        rank_catalog=_rank_catalog(),
        heroes=heroes,
        assets=_assets(),
        epochs=_epochs(),
    )


def test_situational_branch_requires_every_comparative_gate(tmp_path: Path) -> None:
    path = tmp_path / "build-evidence.json"
    document = _document()
    branch = {
        "threat": "healing",
        "item_id": 103,
        "enemy_hero_id": 7,
        "enemy_scope": "whole_enemy_team",
        "phase": 1,
        "tier": 1,
        "mechanic_ref": "item/103/healing-reduction",
        "enemy_mechanics_refs": ["asset:ability:7:description"],
        "comparator": "same-tier default continuation or save",
        "comparator_item_id": 101,
        "comparison_support": 20,
        "same_opportunity": True,
        "support": 20,
        "effective_support": 20.0,
        "overlap": 0.5,
        "stable": True,
        "comparative_interval": [0.01, 0.06],
        "fold_comparative_estimates": {
            "train": 0.03,
            "validation": 0.04,
            "test": 0.02,
        },
        "fold_support": {
            "train": {"item": 20, "comparator": 20},
            "validation": {"item": 20, "comparator": 20},
            "test": {"item": 20, "comparator": 20},
        },
        "trigger": "Enemy healing is observed.",
        "replacement": "Replace the next optional purchase.",
        "execution": "Apply healing reduction after contact.",
        "failure_condition": "Skip when healing is not material.",
    }
    document["heroes"][0]["builds"][0]["situational_policy"]["branches"] = [branch]
    _refingerprint(document)
    _write(path, document)

    catalog = load_build_evidence(path)
    assert catalog.heroes[13].situational_policy is not None
    assert catalog.heroes[13].situational_policy.branches[0].threat == "healing"

    baseline = dict(branch)
    for changes, error in (
        ({"overlap": 0.49}, "unqualified situational branch"),
        ({"same_opportunity": False}, "unqualified situational branch"),
        ({"stable": False}, "unqualified situational branch"),
        ({"support": 19}, "situational support"),
        ({"effective_support": 19.0}, "effective support"),
        ({"comparison_support": 19}, "comparison support"),
        (
            {
                "fold_comparative_estimates": {
                    "train": 0.03,
                    "validation": 0.04,
                    "test": -0.02,
                }
            },
            "unstable situational fold evidence",
        ),
        (
            {
                "fold_support": {
                    "train": {"item": 20, "comparator": 20},
                    "validation": {"item": 20, "comparator": 20},
                    "test": {"item": 19, "comparator": 20},
                }
            },
            "situational test item support",
        ),
        ({"comparative_interval": [-0.01, 0.06]}, "interval"),
        ({"comparative_interval": [0.01, 0.12]}, "interval"),
        ({"mechanic_ref": "item/999/healing"}, "mechanic reference"),
    ):
        branch.clear()
        branch.update(baseline, **changes)
        _refingerprint(document)
        _write(path, document)
        with pytest.raises(ArtifactError, match=error):
            load_build_evidence(path)

    active_assets = [
        {
            **asset,
            "is_active_item": int(asset["id"]) in {103, 102, 201, 202, 301},
        }
        for asset in _assets()
    ]
    active_document = _document(assets=active_assets)
    active_document["heroes"][0]["builds"][0]["situational_policy"]["branches"] = [
        baseline
    ]
    _refingerprint(active_document)
    _write(path, active_document)
    active_catalog = load_build_evidence(path)

    with pytest.raises(ArtifactError, match="illegal situational replacement"):
        select_hero_build(active_catalog.heroes[13], active_assets)
