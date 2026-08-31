from __future__ import annotations

import hashlib
import math
from typing import cast

from .artifacts import ArtifactError
from .build_evidence_types import (
    BuildEvidenceCatalog,
    CoreCandidate,
    HeroBuildEvidence,
    ItemEvidence,
    SelectedHeroBuild,
    nondecreasing_window_schedule,
    reliable_purchase_window,
)
from .build_evidence_values import _required_int
from .mechanics import (
    InventoryState,
    ItemGraph,
    MechanicsError,
    purchase_item,
    schedule_component_path,
)


def _replay_component_path(
    graph: ItemGraph,
    evidence_by_id: dict[int, ItemEvidence],
    path: tuple[int, ...],
) -> InventoryState:
    state = InventoryState()
    for item_id in path:
        if item_id not in evidence_by_id:
            raise MechanicsError(f"purchase path item {item_id} lacks evidence")
        missing = [
            component_id
            for component_id in graph.components[item_id]
            if component_id not in state.owned
        ]
        if missing:
            raise MechanicsError(
                f"purchase path item {item_id} precedes components {missing}"
            )
        state = purchase_item(graph, state, item_id)
    return state


def _expand_component_path(
    graph: ItemGraph,
    targets: tuple[int, ...],
    evidence_by_id: dict[int, ItemEvidence],
) -> tuple[int, ...]:
    priorities = {
        item_id: (
            item.selection_median_valid_buy_net_worth
            if item.selection_median_valid_buy_net_worth is not None
            else math.inf,
            item.selection_median_buy_time_s
            if item.selection_median_buy_time_s is not None
            else math.inf,
            item_id,
        )
        for item_id, item in evidence_by_id.items()
    }
    return schedule_component_path(graph, targets, priorities)


def _select_core_candidate(
    graph: ItemGraph,
    evidence: HeroBuildEvidence,
    by_id: dict[int, ItemEvidence],
) -> tuple[CoreCandidate, tuple[int, ...], int]:
    selected_order = evidence.core_policy.default_item_ids
    candidate = CoreCandidate(
        item_ids=tuple(sorted(selected_order)),
        joint_matches=evidence.core_policy.default_matches,
    )
    cost = sum(graph.require(item_id).cost for item_id in candidate.item_ids)
    if cost > evidence.median_final_net_worth:
        raise ArtifactError(
            f"hero {evidence.hero_id} default core exceeds cohort wealth"
        )
    try:
        candidate_path = _expand_component_path(graph, selected_order, by_id)
        state = _replay_component_path(graph, by_id, candidate_path)
    except MechanicsError as error:
        raise ArtifactError(
            f"hero {evidence.hero_id} has an illegal state-aware core: {error}"
        ) from error
    if len(candidate_path) != len(set(candidate_path)) or set(state.owned) != set(
        candidate.item_ids
    ):
        raise ArtifactError(f"hero {evidence.hero_id} has no legal state-aware core")
    return candidate, selected_order, cost


def _validate_item_assets(
    evidence: HeroBuildEvidence,
    assets_by_id: dict[int, dict[str, object]],
) -> None:
    for item in evidence.items:
        asset = assets_by_id.get(item.item_id)
        if (
            asset is None
            or str(asset.get("name") or "") != item.item
            or _required_int(asset.get("item_tier"), "asset tier") != item.tier
            or _required_int(asset.get("cost"), "asset cost") != item.cost
            or str(asset.get("item_slot_type") or "unknown").casefold() != item.slot
            or bool(asset.get("is_active_item")) != item.active
        ):
            raise ArtifactError(
                f"hero {evidence.hero_id} item {item.item_id} conflicts with assets"
            )


def _replay_selected_path(
    graph: ItemGraph,
    evidence: HeroBuildEvidence,
    by_id: dict[int, ItemEvidence],
    selected: CoreCandidate,
    selected_order: tuple[int, ...],
) -> tuple[int, ...]:
    window_bounds: dict[int, tuple[float, float]] = {}
    for item in by_id.values():
        window = reliable_purchase_window(item)
        if window is not None:
            window_bounds[item.item_id] = window
    path_ids = (
        evidence.sequence_policy.default_path
        if evidence.sequence_policy is not None
        else _expand_component_path(graph, selected_order, by_id)
    )
    if len(path_ids) != len(set(path_ids)):
        raise ArtifactError(
            f"hero {evidence.hero_id} component-expanded path repeats an item"
        )
    if nondecreasing_window_schedule(path_ids, window_bounds) is None:
        raise ArtifactError(
            f"hero {evidence.hero_id} component-expanded path violates "
            "first-ownership soul windows"
        )
    try:
        state = _replay_component_path(graph, by_id, path_ids)
    except MechanicsError as error:
        raise ArtifactError(
            f"hero {evidence.hero_id} has an invalid component-expanded path: {error}"
        ) from error
    if set(state.owned) == set(selected.item_ids):
        return path_ids
    fallback = _expand_component_path(graph, selected_order, by_id)
    if len(fallback) != len(set(fallback)):
        raise ArtifactError(
            f"hero {evidence.hero_id} component-expanded path repeats an item"
        )
    if nondecreasing_window_schedule(fallback, window_bounds) is None:
        raise ArtifactError(
            f"hero {evidence.hero_id} fallback path violates first-ownership "
            "soul windows"
        )
    state = _replay_component_path(graph, by_id, fallback)
    if set(state.owned) != set(selected.item_ids):
        raise ArtifactError(
            f"hero {evidence.hero_id} component-expanded path does not end in CORE"
        )
    return fallback


def _tier_selection(
    evidence: HeroBuildEvidence,
    tier: int,
    core_ids: set[int],
    optional_core_ids: set[int],
    *,
    graph: ItemGraph,
    visible_higher_tier_ids: set[int],
) -> tuple[ItemEvidence, ...]:
    def has_visible_upgrade(item: ItemEvidence) -> bool:
        upgrades = set(graph.children[item.item_id])
        return not upgrades or bool(upgrades & visible_higher_tier_ids)

    by_id = {item.item_id: item for item in evidence.items}
    membership = tuple(
        by_id[item_id] for item_id in evidence.tier_policy.item_ids_by_tier[tier]
    )
    if any(
        item.item_id in core_ids
        or item.item_id in optional_core_ids
        or not has_visible_upgrade(item)
        for item in membership
    ):
        raise ArtifactError(
            f"hero {evidence.hero_id} has an invalid Tier {tier} policy"
        )
    expected_order = tuple(
        sorted(
            membership,
            key=lambda item: (
                reliable_purchase_window(item) is None,
                (
                    item.selection_median_valid_buy_net_worth
                    if reliable_purchase_window(item) is not None
                    and item.selection_median_valid_buy_net_worth is not None
                    else math.inf
                ),
                (
                    item.selection_median_buy_time_s
                    if reliable_purchase_window(item) is not None
                    and item.selection_median_buy_time_s is not None
                    else math.inf
                ),
                item.item_id,
            ),
        )
    )
    if membership != expected_order:
        raise ArtifactError(
            f"hero {evidence.hero_id} Tier {tier} policy order is not deterministic"
        )
    return membership


def _validate_situational_replacements(
    graph: ItemGraph,
    evidence: HeroBuildEvidence,
    by_id: dict[int, ItemEvidence],
    selected_order: tuple[int, ...],
) -> None:
    branches = (
        evidence.situational_policy.branches if evidence.situational_policy else ()
    )
    for branch in branches:
        replacement = tuple(
            branch.item_id if item_id == branch.comparator_item_id else item_id
            for item_id in selected_order
        )
        try:
            path = _expand_component_path(graph, replacement, by_id)
            state = _replay_component_path(graph, by_id, path)
        except MechanicsError as error:
            raise ArtifactError(
                f"hero {evidence.hero_id} has an illegal situational replacement"
            ) from error
        legal = len(replacement) == len(set(replacement)) and set(state.owned) == set(
            replacement
        )
        if not legal:
            raise ArtifactError(
                f"hero {evidence.hero_id} has an illegal situational replacement"
            )


def _selected_tiers(
    graph: ItemGraph,
    evidence: HeroBuildEvidence,
    core_ids: set[int],
    optional_core_ids: set[int],
) -> dict[int, tuple[ItemEvidence, ...]]:
    branches = (
        evidence.situational_policy.branches if evidence.situational_policy else ()
    )
    situational_ids = {branch.item_id for branch in branches}
    if situational_ids & core_ids:
        raise ArtifactError(
            f"hero {evidence.hero_id} situational items repeat the selected CORE"
        )
    tiers: dict[int, tuple[ItemEvidence, ...]] = {}
    visible_higher_tier_ids = core_ids | optional_core_ids
    for tier in range(4, 0, -1):
        tiers[tier] = _tier_selection(
            evidence,
            tier,
            core_ids,
            optional_core_ids,
            graph=graph,
            visible_higher_tier_ids=visible_higher_tier_ids,
        )
        visible_higher_tier_ids.update(item.item_id for item in tiers[tier])
    tier_item_ids = {
        item.item_id for tier_items in tiers.values() for item in tier_items
    }
    if not situational_ids <= tier_item_ids:
        raise ArtifactError(
            f"hero {evidence.hero_id} situational items are absent from tier policy"
        )
    return tiers


def select_hero_build(
    evidence: HeroBuildEvidence,
    assets: list[dict[str, object]],
) -> SelectedHeroBuild:
    graph = ItemGraph.from_assets(assets)
    assets_by_id = {
        cast("int", asset["id"]): asset
        for asset in assets
        if isinstance(asset.get("id"), int)
    }
    by_id = {item.item_id: item for item in evidence.items}
    _validate_item_assets(evidence, assets_by_id)

    selected, selected_order, selected_cost = _select_core_candidate(
        graph, evidence, by_id
    )

    _validate_situational_replacements(graph, evidence, by_id, selected_order)

    path_ids = _replay_selected_path(graph, evidence, by_id, selected, selected_order)

    core_ids = set(path_ids)
    optional_core_ids = {
        alternative.item_id for alternative in evidence.core_policy.alternatives
    }
    tiers = _selected_tiers(graph, evidence, core_ids, optional_core_ids)
    return SelectedHeroBuild(
        hero_id=evidence.hero_id,
        path_id=evidence.path_id,
        path_label=evidence.path_label,
        signature_item_ids=evidence.signature_item_ids,
        core=tuple(by_id[item_id] for item_id in selected_order),
        core_purchase_path=tuple(by_id[item_id] for item_id in path_ids),
        tiers=tiers,
        backbone=tuple(
            by_id[item_id] for item_id in evidence.core_policy.backbone_item_ids
        ),
        optional_core=tuple(
            by_id[alternative.item_id]
            for alternative in sorted(
                evidence.core_policy.alternatives,
                key=lambda row: (row.stage, row.item_id),
            )
        ),
        core_alternatives=evidence.core_policy.alternatives,
        backbone_matches=evidence.core_policy.backbone_matches,
        backbone_share=(
            evidence.core_policy.backbone_matches
            / evidence.selection_eligible_player_matches
        ),
        core_joint_matches=selected.joint_matches,
        core_joint_share=(
            selected.joint_matches / evidence.selection_eligible_player_matches
        ),
        median_final_net_worth=evidence.median_final_net_worth,
        core_target_cost=selected_cost,
    )


def evidence_record_sha256(catalog: BuildEvidenceCatalog) -> str:
    return hashlib.sha256(catalog.raw_bytes).hexdigest()
