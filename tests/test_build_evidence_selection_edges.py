from dataclasses import replace
from pathlib import Path

import pytest

from deadlock_build_sync import build_evidence_selection
from deadlock_build_sync.artifacts import ArtifactError
from deadlock_build_sync.build_evidence import load_build_evidence
from deadlock_build_sync.build_evidence_types import (
    HeroBuildEvidence,
    SituationalBranch,
    SituationalPolicy,
    TierPolicyEvidence,
)
from deadlock_build_sync.mechanics import InventoryState, ItemGraph, MechanicsError
from deadlock_build_sync.purchase_guidance_types import PurchaseTiming
from tests.build_evidence_fixtures import _assets, _document, _write


def _hero(path: Path) -> HeroBuildEvidence:
    _write(path, _document())
    return load_build_evidence(path).heroes[13]


def _branch(item_id: int, comparator_id: int, *, tier: int = 1) -> SituationalBranch:
    return SituationalBranch(
        threat="healing",
        item_id=item_id,
        enemy_hero_id=None,
        mechanic_ref=f"item/{item_id}/healing-reduction",
        comparator="default item",
        comparator_item_id=comparator_id,
        comparison_support=20,
        same_opportunity=True,
        support=20,
        effective_support=20.0,
        overlap=0.5,
        stable=True,
        comparative_interval=(0.01, 0.02),
        trigger="Enemy healing",
        replacement="Replace default",
        execution="Apply anti-heal",
        failure_condition="Healing is not material",
        tier=tier,
    )


def test_component_replay_rejects_missing_evidence_and_components(
    tmp_path: Path,
) -> None:
    hero = _hero(tmp_path / "evidence.json")
    evidence_by_id = {item.item_id: item for item in hero.items}
    graph = ItemGraph.from_assets(_assets())
    with pytest.raises(MechanicsError, match="lacks evidence"):
        build_evidence_selection._replay_component_path(graph, evidence_by_id, (999,))

    assets = _assets()
    child = next(asset for asset in assets if asset["id"] == 202)
    child["component_items"] = ["item_t1_1"]
    graph = ItemGraph.from_assets(assets)
    with pytest.raises(MechanicsError, match="precedes components"):
        build_evidence_selection._replay_component_path(graph, evidence_by_id, (202,))


def test_core_selection_wraps_illegal_inventory_state(tmp_path: Path) -> None:
    hero = _hero(tmp_path / "evidence.json")
    assets = _assets()
    for asset in assets:
        if asset["id"] in {101, 102, 201, 202, 301}:
            asset["is_active_item"] = True
    graph = ItemGraph.from_assets(assets)
    by_id = {item.item_id: item for item in hero.items}

    with pytest.raises(ArtifactError, match="illegal state-aware core"):
        build_evidence_selection._select_core_candidate(graph, hero, by_id)


def test_core_selection_checks_the_replayed_final_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hero = _hero(tmp_path / "evidence.json")
    graph = ItemGraph.from_assets(_assets())
    by_id = {item.item_id: item for item in hero.items}
    monkeypatch.setattr(
        build_evidence_selection,
        "_expand_component_path",
        lambda *_args: (101,),
    )

    with pytest.raises(ArtifactError, match="no legal state-aware core"):
        build_evidence_selection._select_core_candidate(graph, hero, by_id)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", "wrong"),
        ("item_tier", 4),
        ("cost", 99),
        ("item_slot_type", "spirit"),
        ("is_active_item", True),
    ],
)
def test_selection_rejects_asset_identity_drift(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    hero = _hero(tmp_path / "evidence.json")
    assets = _assets()
    assets[0][field] = value

    with pytest.raises(ArtifactError, match="conflicts with assets"):
        build_evidence_selection.select_hero_build(hero, assets)


def test_selected_path_rejects_duplicate_and_invalid_sequence_paths(
    tmp_path: Path,
) -> None:
    hero = _hero(tmp_path / "evidence.json")
    sequence = hero.sequence_policy
    assert sequence is not None
    graph = ItemGraph.from_assets(_assets())
    by_id = {item.item_id: item for item in hero.items}
    selected, order, _ = build_evidence_selection._select_core_candidate(
        graph, hero, by_id
    )

    duplicate = replace(
        hero, sequence_policy=replace(sequence, default_path=(101, 101))
    )
    with pytest.raises(ArtifactError, match="invalid component-expanded path"):
        build_evidence_selection._replay_selected_path(
            graph, duplicate, by_id, selected, order
        )

    unknown = replace(hero, sequence_policy=replace(sequence, default_path=(999,)))
    with pytest.raises(ArtifactError, match="invalid component-expanded path"):
        build_evidence_selection._replay_selected_path(
            graph, unknown, by_id, selected, order
        )


@pytest.mark.parametrize("timing", [(), (PurchaseTiming(103, 20, (20, 0)),)])
def test_selected_path_rejects_incomplete_core_without_fallback(
    tmp_path: Path, timing: tuple[PurchaseTiming, ...]
) -> None:
    hero = _hero(tmp_path / "evidence.json")
    assert hero.sequence_policy is not None
    incomplete = replace(
        hero,
        sequence_policy=replace(hero.sequence_policy, default_path=(101,)),
        purchase_timing=timing,
    )
    graph = ItemGraph.from_assets(_assets())
    by_id = {item.item_id: item for item in hero.items}
    selected, order, _ = build_evidence_selection._select_core_candidate(
        graph, hero, by_id
    )
    with pytest.raises(
        ArtifactError, match="does not end in CORE; refresh-evidence is required"
    ):
        build_evidence_selection._replay_selected_path(
            graph, incomplete, by_id, selected, order
        )


def test_tier_selection_checks_core_overlap_and_order(tmp_path: Path) -> None:
    hero = _hero(tmp_path / "evidence.json")
    graph = ItemGraph.from_assets(_assets())
    first = hero.tier_policy.item_ids_by_tier[1][0]
    with pytest.raises(ArtifactError, match="invalid Tier 1 policy"):
        build_evidence_selection._tier_selection(
            hero,
            1,
            {first},
            set(),
            graph=graph,
            visible_higher_tier_ids=set(graph.nodes),
        )

    membership = dict(hero.tier_policy.item_ids_by_tier)
    membership[1] = tuple(reversed(membership[1]))
    reordered = replace(hero, tier_policy=TierPolicyEvidence(membership))
    with pytest.raises(ArtifactError, match="order is not deterministic"):
        build_evidence_selection._tier_selection(
            reordered,
            1,
            set(),
            set(),
            graph=graph,
            visible_higher_tier_ids=set(graph.nodes),
        )


def test_situational_selection_checks_replacement_and_tier_membership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hero = _hero(tmp_path / "evidence.json")
    graph = ItemGraph.from_assets(_assets())
    by_id = {item.item_id: item for item in hero.items}
    selected_order = hero.core_policy.default_item_ids
    duplicate = _branch(102, 101)
    evidence = replace(hero, situational_policy=SituationalPolicy((duplicate,), ()))
    monkeypatch.setattr(
        build_evidence_selection,
        "_expand_component_path",
        lambda *_args: (101,),
    )
    monkeypatch.setattr(
        build_evidence_selection,
        "_replay_component_path",
        lambda *_args: InventoryState((101,)),
    )
    with pytest.raises(ArtifactError, match="illegal situational replacement"):
        build_evidence_selection._validate_situational_replacements(
            graph, evidence, by_id, selected_order
        )

    core_overlap = replace(
        hero,
        situational_policy=SituationalPolicy((_branch(101, 102),), ()),
    )
    with pytest.raises(ArtifactError, match="repeat the selected CORE"):
        build_evidence_selection._selected_tiers(
            graph, core_overlap, set(selected_order), set()
        )

    absent = replace(
        hero,
        situational_policy=SituationalPolicy((_branch(999, 101),), ()),
    )
    with pytest.raises(ArtifactError, match="absent from tier policy"):
        build_evidence_selection._selected_tiers(graph, absent, set(), set())
