from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from deadlock_build_sync.artifacts import ArtifactError
from deadlock_build_sync.build_evidence import (
    load_build_evidence,
    nondecreasing_window_schedule,
    reliable_purchase_window,
    select_hero_build,
)
from deadlock_build_sync.value_validation import (
    integer,
)
from tests.build_evidence_fixtures import (
    _assets,
    _document,
    _first_item,
    _refingerprint,
    _write,
)

if TYPE_CHECKING:
    from pathlib import Path


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
    ]
    assert selected.core_joint_matches == 80
    assert selected.core_joint_share == 0.10
    assert selected.core_target_cost == 12_000
    assert {tier: len(items) for tier, items in selected.tiers.items()} == {
        1: 9,
        2: 9,
        3: 9,
        4: 10,
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
    item = _first_item(document)
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
    _write(path, _document(median_final_net_worth=10_000))

    catalog = load_build_evidence(path)
    hero = catalog.heroes[13]
    assets = _assets()
    with pytest.raises(ArtifactError, match="exceeds cohort wealth"):
        select_hero_build(hero, assets)


def test_sparse_supported_tiers_do_not_require_filler(tmp_path: Path) -> None:
    path = tmp_path / "build-evidence.json"
    sparse_assets = [asset for asset in _assets() if integer(asset["id"]) % 100 <= 3]
    document = _document(assets=sparse_assets)
    _write(path, document)

    selected = select_hero_build(load_build_evidence(path).heroes[13], _assets())

    assert {tier: len(items) for tier, items in selected.tiers.items()} == {
        1: 1,
        2: 1,
        3: 1,
        4: 3,
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
    alternative: dict[str, object] = {
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
