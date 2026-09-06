from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from deadlock_build_sync.build_evidence import (
    CORE_POLICY_VERSION,
    SEQUENCE_POLICY_VERSION,
)
from deadlock_build_sync.mechanics_compatibility import (
    hero_item_affinity_scores,
)
from deadlock_build_sync.value_validation import (
    integer,
    object_dict,
    object_list,
)

from .build_paths import DiscoveredBuildPath
from .core_policy import (
    complete_default_core,
    select_supported_backbone,
)
from .production_policy import (
    _item_payload,
    _path_cohort_summary,
    _purchase_priorities,
    _purchase_window_bounds,
    _tier_policy,
)
from .production_sequence import (
    _complete_priorities,
    _core_target_order,
    _expanded_default_path,
    _sequence_evaluation,
    _sequence_rows,
)
from .production_situational import _situational_policy
from .production_sources import (
    SEQUENCE_MINIMUM_SUPPORT,
    UnsupportedBuildPathError,
    _HeroExportContext,
    _path_item_metrics,
)
from .production_storage import _core_alternatives, _core_decisions
from .production_timing import timing_payload

if TYPE_CHECKING:
    import duckdb
    import polars as pl


def _resolved_path_label(
    raw_label: str,
    path: DiscoveredBuildPath,
    label_counts: Counter[str],
    assets_by_id: dict[int, dict[str, object]],
) -> str:
    if label_counts[raw_label] <= 1 or not path.signature_item_ids:
        return raw_label
    asset = assets_by_id.get(path.signature_item_ids[0], {})
    item_name = asset.get("name")
    if isinstance(item_name, str) and item_name.strip():
        return f"{raw_label} / {item_name.strip()}"
    return raw_label


def _supported_route_members(
    inventories: dict[tuple[int, int], tuple[int, ...]],
    item_ids: tuple[int, ...],
    folds_by_match: dict[int, str],
) -> set[tuple[int, int]]:
    required = set(item_ids)
    return {
        identity
        for identity, inventory in inventories.items()
        if folds_by_match[identity[0]] == "train" and required <= set(inventory)
    }


def _core_evaluation_contract() -> dict[str, object]:
    return {
        "chronological_split": "60/20/20 by match start",
        "cross_fitting": "five match-group folds within each chronological fold",
        "estimand": "pairwise like-state win-probability contrast at a logged purchase opportunity",
        "target_trial": {
            "eligibility": "first unambiguous purchase in a hero/phase/tier decision stratum",
            "time_zero": "last telemetry state observed no later than the purchase",
            "candidate_slate": "same-tier catalog items plus save",
            "treatments": "admitted item versus default comparator; save remains in the logged slate",
            "assignment_model": "cross-fitted behavior propensity from pre-decision state",
            "follow_up": "through match completion",
            "outcome": "team win indicator",
            "censoring": "no post-decision state is used; unobserved save choices are not estimated",
            "estimand": "observational pairwise average win-probability contrast over overlap states",
        },
        "support_floor": 20,
        "effective_support_floor": 20,
        "overlap_floor": 0.5,
        "maximum_standardized_mean_difference": 0.1,
        "maximum_interval_width": 0.1,
        "weight_clips": [5, 10, 20],
        "outcome_claim": "assumption-dependent; not proof of causation",
    }


def _build_path_payload(
    con: duckdb.DuckDBPyConnection,
    hero_id: int,
    hero: dict[str, object],
    path: DiscoveredBuildPath,
    raw_label: str,
    label_counts: Counter[str],
    inventories: dict[tuple[int, int], tuple[int, ...]],
    context: _HeroExportContext,
    core_decisions: pl.DataFrame | None = None,
    situational_evidence: tuple[pl.DataFrame, pl.DataFrame] | None = None,
) -> dict[str, object]:
    path_inventories = {identity: inventories[identity] for identity in path.member_ids}
    path_metrics = _path_item_metrics(con, path.member_ids)
    eligible_matches, median_final_net_worth = _path_cohort_summary(
        con, path.member_ids
    )
    fold_eligible_matches = {
        fold: int(path.fold_support.get(fold, 0))
        for fold in ("train", "validation", "test")
    }
    selection_eligible_matches = (
        fold_eligible_matches["train"] + fold_eligible_matches["validation"]
    )
    priorities = _complete_priorities(
        _purchase_priorities(path_metrics), context.item_graph
    )
    window_bounds = _purchase_window_bounds(path_metrics)
    try:
        backbone = select_supported_backbone(
            path_inventories,
            context.folds_by_match,
            context.item_graph,
            mechanic_affinity=hero_item_affinity_scores(hero, context.normal_assets),
        )
        default_item_ids, default_matches, completion_audit = complete_default_core(
            backbone,
            path_inventories,
            context.folds_by_match,
            context.item_graph,
            context.item_costs,
            median_final_net_worth,
            target_cost=context.target_core_cost,
        )
    except RuntimeError as error:
        raise UnsupportedBuildPathError(str(error)) from error
    state_candidate: dict[str, object] = {
        "item_ids": list(default_item_ids),
        "joint_matches": default_matches,
    }
    target_order, route_diagnostics = _core_target_order(
        con,
        hero_id,
        state_candidate,
        _supported_route_members(
            path_inventories, default_item_ids, context.folds_by_match
        ),
        context.item_graph,
        priorities,
        window_bounds,
    )
    alternatives, alternative_audit = _core_alternatives(
        core_decisions if core_decisions is not None else _core_decisions(con, hero_id),
        target_order,
        backbone.item_ids,
        path_metrics,
        context.mechanics_assets_by_id,
        context.item_graph,
        priorities,
    )
    expanded_default_path = tuple(
        _expanded_default_path(target_order, path_metrics, context.item_graph)
    )
    tier_policy = _tier_policy(
        hero_id,
        path_metrics,
        expanded_default_path,
        frozenset(integer(row["item_id"]) for row in alternatives),
        context.item_graph,
        fold_eligible_matches,
    )
    item_ids_by_tier = object_dict(tier_policy["item_ids_by_tier"])
    if item_ids_by_tier is None:
        raise TypeError("tier policy item groups must be a dictionary")
    tier_item_ids: set[int] = set()
    for value in item_ids_by_tier.values():
        item_ids = object_list(value)
        if item_ids is None:
            raise TypeError("each tier policy item group must be a list")
        tier_item_ids.update(integer(item_id) for item_id in item_ids)
    situational_policy = _situational_policy(
        context.paths,
        hero_id,
        context.normal_assets,
        excluded_item_ids=frozenset(default_item_ids),
        eligible_item_ids=frozenset(tier_item_ids),
        comparator_item_ids=frozenset(target_order),
        default_item_ids=target_order,
        graph=context.item_graph,
        priorities=priorities,
        enemy_threat_evidence=context.enemy_threat_evidence,
        con=con,
        preloaded_evidence=situational_evidence,
    )
    selected_completion = next(
        row for row in completion_audit if bool(row.get("selected"))
    )
    return {
        "path_id": path.path_id,
        "path_label": _resolved_path_label(
            raw_label,
            path,
            label_counts,
            context.mechanics_assets_by_id,
        ),
        "signature_item_ids": list(path.signature_item_ids),
        "discovery": path.diagnostics,
        "eligible_player_matches": eligible_matches,
        "selection_eligible_player_matches": selection_eligible_matches,
        "fold_eligible_player_matches": fold_eligible_matches,
        "median_final_net_worth": median_final_net_worth,
        "core_policy": {
            "version": CORE_POLICY_VERSION,
            "backbone_item_ids": list(backbone.item_ids),
            "default_item_ids": list(target_order),
            "backbone_matches": backbone.matches,
            "backbone_fold_matches": backbone.fold_matches,
            "default_matches": default_matches,
            "default_fold_matches": selected_completion["joint_fold_matches"],
            "alternatives": alternatives,
            "candidate_audit": [
                *backbone.audit,
                *completion_audit,
                *alternative_audit,
            ],
            "evaluation": _core_evaluation_contract(),
        },
        "items": [
            _item_payload(
                row,
                context.mechanics_assets_by_id,
                fold_eligible_matches,
            )
            for row in path_metrics.sort("item_id").iter_rows(named=True)
        ],
        "tier_policy": tier_policy,
        "purchase_timing": timing_payload(
            con, hero_id, path.member_ids, expanded_default_path, tier_policy
        ),
        "sequence_policy": {
            "version": SEQUENCE_POLICY_VERSION,
            "minimum_support": SEQUENCE_MINIMUM_SUPPORT,
            "production_model": "deterministic_backoff",
            "component_expanded_default_path": list(expanded_default_path),
            "route_diagnostics": route_diagnostics,
            "transitions": _sequence_rows(con, hero_id, path.member_ids),
            "evaluation": {
                "status": "unevaluated",
                "scope": "exact_runtime_policy",
                "reason": "replay the frozen typed policy on later decision states with quality-report",
                "hero_baseline_diagnostics": _sequence_evaluation(
                    context.paths, hero_id
                ),
                "diagnostic_scope": "hero-wide historical models; not this build policy",
                "claim": "outcome-agnostic next-action imitation; no outcome improvement claim",
            },
        },
        "situational_policy": situational_policy,
    }


def _fallback_build_path(
    inventories: dict[tuple[int, int], tuple[int, ...]],
    folds_by_match: dict[int, str],
) -> DiscoveredBuildPath:
    members = frozenset(inventories)
    return DiscoveredBuildPath(
        "default",
        members,
        (),
        dict(Counter(folds_by_match[identity[0]] for identity in members)),
        {
            "selection": "single-supported-path",
            "fallback": "discovered split lacked a supported legal core",
        },
    )
