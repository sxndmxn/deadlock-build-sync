from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from deadlock_build_sync.artifacts import ArtifactError
from deadlock_build_sync.build_evidence import (
    assert_build_evidence_compatible,
    load_build_evidence,
    select_hero_build,
)
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
    }


def _document(
    *,
    assets: list[dict[str, Any]] | None = None,
    candidates: list[dict[str, Any]] | None = None,
    median_final_net_worth: int = 30_000,
) -> dict[str, Any]:
    current_assets = assets or _assets()
    heroes = [{"id": 13, "name": "Haze"}]
    payload = {
        "schema_version": 1,
        "producer": "deadlock-build-analysis",
        "method": {
            "version": "reconstructed-final-inventory-v2",
            "core_item_count": 8,
            "core_candidate_limit": 64,
            "minimum_core_support": 20,
            "tier_item_count": 10,
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
                "eligible_player_matches": 1_000,
                "median_final_net_worth": median_final_net_worth,
                "core_candidates": candidates
                or [
                    {
                        "item_ids": [101, 102, 201, 202, 301, 302, 401, 402],
                        "joint_matches": 80,
                    }
                ],
                "items": [_item(asset) for asset in current_assets],
            }
        ],
    }
    return {**payload, "artifact_id": sha256_json(payload)}


def _write(path: Path, document: dict[str, Any]) -> None:
    path.write_text(json.dumps(document), encoding="utf-8")


def test_load_and_select_exact_build_layout(tmp_path: Path) -> None:
    path = tmp_path / "build-evidence.json"
    _write(path, _document())

    catalog = load_build_evidence(path)
    selected = select_hero_build(catalog.heroes[13], _assets())

    assert [item.item_id for item in selected.core] == [
        402,
        401,
        302,
        301,
        202,
        201,
        102,
        101,
    ]
    assert selected.core_joint_matches == 80
    assert selected.core_joint_share == 0.08
    assert selected.core_target_cost == 20_000
    assert {tier: len(items) for tier, items in selected.tiers.items()} == {
        1: 10,
        2: 10,
        3: 10,
        4: 10,
    }
    assert [item.item_id for item in selected.tiers[1]] == [
        101,
        102,
        103,
        104,
        105,
        106,
        107,
        108,
        109,
        110,
    ]
    assert 111 not in {item.item_id for item in selected.tiers[1]}
    assert (
        next(
            item for item in catalog.heroes[13].items if item.item_id == 111
        ).observed_outcome_rate
        == 1.0
    )


def test_selection_skips_core_above_median_final_net_worth(tmp_path: Path) -> None:
    path = tmp_path / "build-evidence.json"
    candidates = [
        {"item_ids": list(range(403, 411)), "joint_matches": 90},
        {"item_ids": list(range(101, 109)), "joint_matches": 80},
    ]
    _write(path, _document(candidates=candidates, median_final_net_worth=10_000))

    catalog = load_build_evidence(path)
    selected = select_hero_build(catalog.heroes[13], _assets())

    assert {item.item_id for item in selected.core} == set(range(101, 109))
    assert selected.core_joint_matches == 80


def test_loader_rejects_tampering(tmp_path: Path) -> None:
    path = tmp_path / "build-evidence.json"
    document = _document()
    document["heroes"][0]["items"][0]["wins"] = 999
    _write(path, document)

    with pytest.raises(ArtifactError, match="fingerprint"):
        load_build_evidence(path)


def test_compatibility_rejects_identity_drift(tmp_path: Path) -> None:
    path = tmp_path / "build-evidence.json"
    heroes = [{"id": 13, "name": "Haze"}]
    _write(path, _document())
    catalog = load_build_evidence(path)

    with pytest.raises(ArtifactError, match="patch"):
        assert_build_evidence_compatible(
            catalog,
            patch_identity="new-patch",
            client_version=6_673,
            as_of_timestamp=catalog.as_of_timestamp,
            match_mode=MatchMode.RANKED,
            rank_range=DEFAULT_RANK_RANGE,
            rank_catalog=_rank_catalog(),
            heroes=heroes,
            assets=_assets(),
            epochs=_epochs(),
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
