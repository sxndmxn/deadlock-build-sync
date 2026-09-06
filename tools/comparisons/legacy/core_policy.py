from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from itertools import chain, combinations
from typing import cast

from deadlock_build_sync.mechanics import (
    BASE_INVENTORY_SLOTS,
    InventoryState,
    ItemGraph,
    MechanicsError,
    purchase_item,
    schedule_component_path,
)
from deadlock_build_sync.offline.core_policy_config import (
    CORE_TARGET_TOLERANCE_SHARE,
    MAXIMUM_BACKBONE_SIZE,
    MAXIMUM_TEMPORAL_SHARE_RANGE,
    MINIMUM_BACKBONE_SIZE,
    MINIMUM_EXTENSION_RETENTION,
    MINIMUM_SUPPORT,
    SELECTION_FOLDS,
)
from deadlock_build_sync.offline.core_policy_dr import (
    DrContrast,
    cross_fitted_dr_contrast,
)

__all__ = [
    "BackboneSelection",
    "DrContrast",
    "complete_default_core",
    "cross_fitted_dr_contrast",
    "select_supported_backbone",
]


@dataclass(frozen=True)
class BackboneSelection:
    item_ids: tuple[int, ...]
    matches: int
    fold_matches: dict[str, int]
    audit: tuple[dict[str, object], ...]


def _legal_target(graph: ItemGraph, item_ids: tuple[int, ...]) -> bool:
    priorities = {item_id: (0.0, 0.0, item_id) for item_id in graph.nodes}
    try:
        path = schedule_component_path(graph, item_ids, priorities)
        state = InventoryState()
        for item_id in path:
            state = purchase_item(graph, state, item_id)
    except (KeyError, MechanicsError):
        return False
    return len(path) == len(set(path)) and set(state.owned) == set(item_ids)


type _BackboneRow = tuple[tuple[int, ...], int, dict[str, int]]


def _bundle_support_by_size_and_fold(
    inventories: dict[tuple[int, int], tuple[int, ...]],
    folds_by_match: dict[int, str],
    excluded_item_ids: frozenset[int],
) -> dict[int, dict[str, Counter[tuple[int, ...]]]]:
    inventories_by_fold: dict[str, list[tuple[int, ...]]] = {
        fold: [] for fold in ("train", "validation", "test")
    }
    for (match_id, _), inventory in inventories.items():
        distinct = tuple(sorted(set(inventory) - excluded_item_ids))
        if len(distinct) < MINIMUM_BACKBONE_SIZE:
            continue
        inventories_by_fold[folds_by_match[match_id]].append(distinct)
    result: dict[int, dict[str, Counter[tuple[int, ...]]]] = {}
    for size in range(MINIMUM_BACKBONE_SIZE, MAXIMUM_BACKBONE_SIZE + 1):
        fold_counts: dict[str, Counter[tuple[int, ...]]] = {}
        for fold, fold_inventories in inventories_by_fold.items():
            fold_counts[fold] = Counter(
                chain.from_iterable(
                    combinations(inventory, size)
                    for inventory in fold_inventories
                    if len(inventory) >= size
                )
            )
        result[size] = fold_counts
    return result


def _qualified_backbones_at_size(
    size: int,
    fold_counts: dict[str, Counter[tuple[int, ...]]],
    fold_totals: Counter[str],
    graph: ItemGraph,
    affinity: dict[int, int],
    minimum_support: int,
    audit: list[dict[str, object]],
) -> list[_BackboneRow]:
    qualified = []
    ranked = sorted(fold_counts["train"].items(), key=lambda row: (-row[1], row[0]))[
        :256
    ]
    for item_ids, training_support in ranked:
        if training_support < minimum_support:
            break
        fold_matches = {
            fold: matches[item_ids] for fold, matches in fold_counts.items()
        }
        support = sum(fold_matches[fold] for fold in SELECTION_FOLDS)
        fold_shares = [
            fold_matches[fold] / fold_totals[fold]
            for fold in SELECTION_FOLDS
            if fold_totals[fold]
        ]
        gates = {
            "mechanically_legal": _legal_target(graph, item_ids),
            "effective_support": all(
                fold_matches[fold] >= minimum_support for fold in SELECTION_FOLDS
            ),
            "temporally_stable": bool(fold_shares)
            and max(fold_shares) - min(fold_shares) <= MAXIMUM_TEMPORAL_SHARE_RANGE,
        }
        admitted = all(gates.values())
        audit.append({
            "item_ids": list(item_ids),
            "size": size,
            "matches": support,
            "fold_matches": fold_matches,
            "mechanic_affinity": sum(affinity.get(item_id, 0) for item_id in item_ids),
            "gates": gates,
            "admitted": admitted,
        })
        if admitted:
            qualified.append((item_ids, support, fold_matches))
    return sorted(
        qualified,
        key=lambda row: (
            -row[1],
            -sum(affinity.get(item_id, 0) for item_id in row[0]),
            row[0],
        ),
    )


def select_supported_backbone(
    inventories: dict[tuple[int, int], tuple[int, ...]],
    folds_by_match: dict[int, str],
    graph: ItemGraph,
    *,
    minimum_support: int = MINIMUM_SUPPORT,
    excluded_item_ids: frozenset[int] = frozenset(),
    mechanic_affinity: dict[int, int] | None = None,
) -> BackboneSelection:
    """Select the longest stable bundle before support falls off an empirical cliff."""
    affinity = mechanic_affinity or {}
    fold_totals = Counter(folds_by_match[identity[0]] for identity in inventories)
    ranked_by_size: dict[int, list[tuple[tuple[int, ...], int, dict[str, int]]]] = {}
    audit: list[dict[str, object]] = []
    fold_counts_by_size = _bundle_support_by_size_and_fold(
        inventories,
        folds_by_match,
        excluded_item_ids,
    )
    for size in range(MINIMUM_BACKBONE_SIZE, MAXIMUM_BACKBONE_SIZE + 1):
        ranked_by_size[size] = _qualified_backbones_at_size(
            size,
            fold_counts_by_size[size],
            fold_totals,
            graph,
            affinity,
            minimum_support,
            audit,
        )
    if not ranked_by_size[MINIMUM_BACKBONE_SIZE]:
        raise RuntimeError("hero has no mechanically legal, temporally stable backbone")
    selected = ranked_by_size[MINIMUM_BACKBONE_SIZE][0]
    for size in range(MINIMUM_BACKBONE_SIZE + 1, MAXIMUM_BACKBONE_SIZE + 1):
        extensions = [
            row
            for row in ranked_by_size[size]
            if set(selected[0]) < set(row[0])
            and row[1] / selected[1] >= MINIMUM_EXTENSION_RETENTION
        ]
        if not extensions:
            break
        selected = min(
            extensions,
            key=lambda row: (
                -row[1],
                -sum(affinity.get(item_id, 0) for item_id in row[0]),
                row[0],
            ),
        )
    return BackboneSelection(
        item_ids=selected[0],
        matches=selected[1],
        fold_matches=selected[2],
        audit=tuple(audit),
    )


type _CompletionScore = tuple[int, tuple[float, float], tuple[int, ...], int]


def _addition_support(
    backbone: BackboneSelection,
    supporting: dict[tuple[int, int], tuple[int, ...]],
    folds_by_match: dict[int, str],
    excluded_item_ids: frozenset[int],
) -> tuple[Counter[int], dict[str, Counter[int]], list[int]]:
    item_counts: Counter[int] = Counter()
    fold_item_counts = {fold: Counter() for fold in ("train", "validation", "test")}
    backbone_ids = set(backbone.item_ids)
    for (match_id, _), inventory in supporting.items():
        additions = set(inventory) - backbone_ids - excluded_item_ids
        item_counts.update(additions)
        fold_item_counts[folds_by_match[match_id]].update(additions)
    selection_counts = fold_item_counts["train"] + fold_item_counts["validation"]
    ranked = sorted(
        fold_item_counts["train"],
        key=lambda item_id: (-fold_item_counts["train"][item_id], item_id),
    )
    return selection_counts, fold_item_counts, ranked[:20]


def _joint_addition_support(
    backbone: BackboneSelection,
    supporting: dict[tuple[int, int], tuple[int, ...]],
    folds_by_match: dict[int, str],
    pool: list[int],
) -> tuple[
    dict[int, Counter[tuple[int, ...]]],
    dict[int, dict[str, Counter[tuple[int, ...]]]],
]:
    pool_set = set(pool)
    backbone_ids = set(backbone.item_ids)
    joint_counts: dict[int, Counter[tuple[int, ...]]] = {}
    joint_fold_counts: dict[int, dict[str, Counter[tuple[int, ...]]]] = {}
    for needed in range(BASE_INVENTORY_SLOTS - len(backbone.item_ids) + 1):
        counts: Counter[tuple[int, ...]] = Counter()
        fold_counts = {fold: Counter() for fold in ("train", "validation", "test")}
        for (match_id, _), inventory in supporting.items():
            available = tuple(sorted((set(inventory) - backbone_ids) & pool_set))
            if len(available) < needed:
                continue
            bundles = tuple(combinations(available, needed))
            counts.update(bundles)
            fold_counts[folds_by_match[match_id]].update(bundles)
        joint_counts[needed] = fold_counts["train"]
        joint_fold_counts[needed] = fold_counts
    return joint_counts, joint_fold_counts


def _completion_target_metrics(
    total_cost: int, target_cost: int | None
) -> tuple[int | None, bool | None]:
    if target_cost is None:
        return None, None
    distance = abs(total_cost - target_cost)
    return distance, distance <= target_cost * CORE_TARGET_TOLERANCE_SHARE


def _evaluate_completion(
    backbone: BackboneSelection,
    additions: tuple[int, ...],
    joint: int,
    joint_fold_matches: dict[str, int],
    supporting_fold_totals: Counter[str],
    item_counts: Counter[int],
    fold_item_counts: dict[str, Counter[int]],
    graph: ItemGraph,
    item_costs: dict[int, int],
    maximum_cost: int,
    target_cost: int | None,
) -> tuple[dict[str, object], _CompletionScore | None]:
    target = (*backbone.item_ids, *additions)
    fold_shares = [
        joint_fold_matches[fold] / supporting_fold_totals[fold]
        for fold in SELECTION_FOLDS
        if supporting_fold_totals[fold]
    ]
    total_cost = sum(item_costs.get(item_id, maximum_cost + 1) for item_id in target)
    gates = {
        "mechanically_legal": _legal_target(graph, target),
        "within_cohort_wealth": total_cost <= maximum_cost,
        "conditional_support": all(
            item_counts[item_id] >= MINIMUM_SUPPORT for item_id in additions
        ),
        "temporal_support": all(
            fold_item_counts[fold][item_id] >= MINIMUM_SUPPORT
            for fold in SELECTION_FOLDS
            for item_id in additions
        ),
        "joint_effective_support": all(
            joint_fold_matches[fold] >= MINIMUM_SUPPORT for fold in SELECTION_FOLDS
        ),
        "joint_temporal_stability": bool(fold_shares)
        and max(fold_shares) - min(fold_shares) <= MAXIMUM_TEMPORAL_SHARE_RANGE,
    }
    supports = tuple(item_counts[item_id] for item_id in additions)
    if supports:
        conditional_score = float(min(supports)), sum(supports) / len(supports)
    else:
        conditional_score = float(backbone.matches), float(backbone.matches)
    distance, within_band = _completion_target_metrics(total_cost, target_cost)
    admitted = all(gates.values())
    record = {
        "item_ids": list(target),
        "added_item_ids": list(additions),
        "conditional_support": {
            str(item_id): item_counts[item_id] for item_id in additions
        },
        "joint_matches": joint,
        "joint_fold_matches": joint_fold_matches,
        "total_cost": total_cost,
        "target_cost": target_cost,
        "target_distance": distance,
        "within_target_band": within_band,
        "gates": gates,
        "admitted": admitted,
    }
    score = (joint, conditional_score, additions, total_cost) if admitted else None
    return record, score


def _eligible_completions(
    candidates: list[_CompletionScore], target_cost: int | None
) -> list[_CompletionScore]:
    if target_cost is None:
        return candidates
    in_band = [
        row
        for row in candidates
        if abs(row[3] - target_cost) <= target_cost * CORE_TARGET_TOLERANCE_SHARE
    ]
    if in_band:
        return in_band
    closest_distance = min(abs(row[3] - target_cost) for row in candidates)
    return [row for row in candidates if abs(row[3] - target_cost) == closest_distance]


def complete_default_core(
    backbone: BackboneSelection,
    inventories: dict[tuple[int, int], tuple[int, ...]],
    folds_by_match: dict[int, str],
    graph: ItemGraph,
    item_costs: dict[int, int],
    maximum_cost: int,
    *,
    excluded_item_ids: frozenset[int] = frozenset(),
    target_cost: int | None = None,
) -> tuple[tuple[int, ...], int, tuple[dict[str, object], ...]]:
    """Complete the backbone near the economy target while reserving situational room."""
    supporting = {
        identity: inventory
        for identity, inventory in inventories.items()
        if set(backbone.item_ids) <= set(inventory)
    }
    item_counts, fold_item_counts, pool = _addition_support(
        backbone, supporting, folds_by_match, excluded_item_ids
    )
    joint_counts, joint_fold_counts = _joint_addition_support(
        backbone, supporting, folds_by_match, pool
    )
    supporting_fold_totals = Counter(
        folds_by_match[identity[0]] for identity in supporting
    )
    candidates: list[_CompletionScore] = []
    audit: list[dict[str, object]] = []
    for needed in joint_counts:
        for additions in combinations(pool, needed):
            bundle = tuple(sorted(additions))
            joint_fold_matches = {
                fold: fold_counts[bundle]
                for fold, fold_counts in joint_fold_counts[needed].items()
            }
            joint = sum(joint_fold_matches[fold] for fold in SELECTION_FOLDS)
            record, score = _evaluate_completion(
                backbone,
                additions,
                joint,
                joint_fold_matches,
                supporting_fold_totals,
                item_counts,
                fold_item_counts,
                graph,
                item_costs,
                maximum_cost,
                target_cost,
            )
            audit.append(record)
            if score is not None:
                candidates.append(score)
    if not candidates:
        raise RuntimeError("hero backbone has no supported legal core completion")
    eligible = _eligible_completions(candidates, target_cost)
    joint, _, additions, _ = max(
        eligible,
        key=lambda row: (row[0], row[1], tuple(-item for item in row[2])),
    )
    selected_ids = {*backbone.item_ids, *additions}
    selected_audit = next(
        row
        for row in audit
        if bool(row["admitted"])
        and set(cast("list[int]", row["item_ids"])) == selected_ids
    )
    selected_audit["selected"] = True
    ranked_audit = sorted(
        audit,
        key=lambda row: (
            not bool(row["admitted"]),
            -sum(cast("dict[str, int]", row["conditional_support"]).values()),
            tuple(cast("list[int]", row["item_ids"])),
        ),
    )
    bounded_audit = [selected_audit]
    bounded_audit.extend(row for row in ranked_audit if row is not selected_audit)
    bounded_audit = bounded_audit[:128]
    return (*backbone.item_ids, *additions), joint, tuple(bounded_audit)
