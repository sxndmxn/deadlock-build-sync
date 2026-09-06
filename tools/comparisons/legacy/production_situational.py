from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from deadlock_build_sync.build_evidence import (
    MAX_SITUATIONAL_BRANCHES,
    MECHANIC_RESPONSE_THREATS,
    SITUATIONAL_POLICY_VERSION,
    THREAT_CLASSES,
)
from deadlock_build_sync.mechanics import (
    ItemGraph,
    classify_item_threat_responses,
    conditional_item_decision,
)
from deadlock_build_sync.offline.config import RunPaths
from deadlock_build_sync.value_validation import (
    integer,
    number,
    object_dict,
)

from .production_sequence import _replacement_is_legal
from .production_situational_data import (
    _bounded_comparative_interval,
    _load_situational_evidence,
    _situational_temporal_diagnostic,
)

if TYPE_CHECKING:
    import duckdb
    import polars as pl

    from .production_situational_types import (
        QualifiedSituationalBranch,
        SituationalEvidence,
    )


def _evaluate_situational_response(
    row: dict[str, object],
    response: str,
    diagnostic: dict[str, object],
    temporal: dict[str, object],
    enemy_threat_evidence: dict[int, dict[str, tuple[str, ...]]],
) -> tuple[dict[str, object], QualifiedSituationalBranch | None]:
    item_id = integer(row["item_id"])
    effective = number(diagnostic.get("effective_support") or 0.0)
    state_coverage = number(diagnostic.get("state_coverage") or 0.0)
    comparator_item_id = integer(row.get("comparator_item_id"), default=0)
    comparison_support = integer(row.get("comparison_support"), default=0)
    comparative_interval = _bounded_comparative_interval(row)
    stable = bool(temporal.get("selection_stable"))
    gates = {
        "mechanics": True,
        "same_opportunity": bool(row.get("same_opportunity")),
        "comparator": comparator_item_id > 0,
        "support": integer(row["observations"]) >= 20,
        "comparison_support": comparison_support >= 20,
        "effective_support": effective >= 20,
        "overlap": state_coverage >= 0.5,
        "fold_support": bool(temporal.get("selection_supported")),
        "fold_advantage": bool(temporal.get("selection_positive")),
        "test_support": bool(temporal.get("test_supported")),
        "test_advantage": bool(temporal.get("test_positive")),
        "chronological_stability": stable,
        "bounded_comparative_uncertainty": comparative_interval is not None,
        "comparative_advantage": (
            comparative_interval is not None and comparative_interval[0] > 0
        ),
    }
    passed = all(gates.values())
    threat = MECHANIC_RESPONSE_THREATS[response]
    enemy_id = integer(row["enemy_hero_id"])
    enemy_mechanics_refs = enemy_threat_evidence.get(enemy_id, {}).get(threat, ())
    gates["enemy_mechanics"] = bool(enemy_mechanics_refs)
    passed = all(gates.values())
    comparator = (
        f"same-opportunity item {comparator_item_id} or save"
        if comparator_item_id
        else "unavailable"
    )
    candidate: dict[str, object] = {
        "threat": threat,
        "item_id": item_id,
        "comparator_item_id": comparator_item_id or None,
        "enemy_hero_id": enemy_id,
        "enemy_scope": str(row["scope"]),
        "phase": integer(row["phase"]),
        "tier": integer(row["tier"]),
        "mechanic_ref": f"item/{item_id}/{response}",
        "enemy_mechanics_refs": list(enemy_mechanics_refs),
        "comparator": comparator,
        "support": integer(row["observations"]),
        "comparison_support": comparison_support,
        "effective_support": effective,
        "overlap": state_coverage,
        "stable": stable,
        "comparative_interval": [
            row.get("comparative_interval_low"),
            row.get("comparative_interval_high"),
        ],
        "fold_comparative_estimates": temporal.get("fold_comparative_estimates", {}),
        "fold_support": temporal.get("fold_support", {}),
        "gates": gates,
        "qualified": passed,
        "admitted": False,
    }
    if not passed or comparative_interval is None:
        return candidate, None
    branch: dict[str, object] = {
        "threat": threat,
        "item_id": item_id,
        "enemy_hero_id": enemy_id,
        "enemy_scope": str(row["scope"]),
        "phase": integer(row["phase"]),
        "tier": integer(row["tier"]),
        "mechanic_ref": f"item/{item_id}/{response}",
        "enemy_mechanics_refs": list(enemy_mechanics_refs),
        "comparator": comparator,
        "comparator_item_id": comparator_item_id,
        "comparison_support": comparison_support,
        "same_opportunity": True,
        "support": integer(row["observations"]),
        "effective_support": effective,
        "overlap": state_coverage,
        "stable": stable,
        "comparative_interval": list(comparative_interval),
        "fold_comparative_estimates": temporal.get("fold_comparative_estimates", {}),
        "fold_support": temporal.get("fold_support", {}),
        "trigger": (
            f"Enemy hero {enemy_id} presents material {threat.replace('_', ' ')}."
        ),
        "replacement": (
            f"Choose item {item_id} instead of item {comparator_item_id} "
            "at the matched opportunity."
        ),
        "execution": (
            f"Use the verified {response.replace('_', ' ')} mechanic while the "
            "trigger remains observable."
        ),
        "failure_condition": (
            "Skip when the threat is not material or the compared decision state "
            "no longer matches."
        ),
    }
    score = (
        float(str(row["scope"]) == "same_lane"),
        state_coverage,
        effective,
        number(row["observations"]),
        -float(item_id),
    )
    return candidate, (score, candidate, branch)


def _situational_decision(
    asset: dict[str, object],
    comparator_asset: dict[str, object] | None,
    response: str,
    key: tuple[int, int, str],
    cache: dict[tuple[int, int, str], tuple[str, str, str, str] | None],
) -> tuple[str, str, str, str] | None:
    if key not in cache:
        cache[key] = (
            conditional_item_decision(asset, comparator_asset, response=response)
            if comparator_asset is not None
            else None
        )
    return cache[key]


def _matchup_candidates(
    row: dict[str, object],
    *,
    asset_by_id: dict[int, dict[str, object]],
    responses_by_item: dict[int, frozenset[str]],
    overlap_by_item: dict[int, dict[str, object]],
    stability_by_scope: dict[object, dict[str, object]],
    enemy_threat_evidence: dict[int, dict[str, tuple[str, ...]]],
    decision_cache: dict[tuple[int, int, str], tuple[str, str, str, str] | None],
) -> tuple[list[dict[str, object]], list[QualifiedSituationalBranch]]:
    item_id = integer(row["item_id"])
    comparator_item_id = integer(row.get("comparator_item_id"), default=0)
    asset = asset_by_id.get(item_id)
    if asset is None:
        return [], []
    comparator_asset = asset_by_id.get(comparator_item_id)
    diagnostic = overlap_by_item.get(item_id, {})
    temporal = _situational_temporal_diagnostic(row, stability_by_scope)
    candidates: list[dict[str, object]] = []
    qualified: list[QualifiedSituationalBranch] = []
    for response in sorted(responses_by_item[item_id]):
        candidate, branch = _evaluate_situational_response(
            row,
            response,
            diagnostic,
            temporal,
            enemy_threat_evidence,
        )
        key = item_id, comparator_item_id, response
        decision = _situational_decision(
            asset,
            comparator_asset,
            response,
            key,
            decision_cache,
        )
        _candidate_gates(candidate)["decision_copy"] = decision is not None
        candidate["qualified"] = bool(candidate["qualified"] and decision)
        candidates.append(candidate)
        if branch is not None and decision is not None:
            qualified.append(branch)
    return candidates, qualified


def _eligible_situational_item(
    item_id: int,
    excluded_item_ids: frozenset[int],
    eligible_item_ids: frozenset[int] | None,
) -> bool:
    if item_id in excluded_item_ids:
        return False
    return eligible_item_ids is None or item_id in eligible_item_ids


def _collect_situational_candidates(
    evidence: SituationalEvidence,
    assets: list[dict[str, object]],
    excluded_item_ids: frozenset[int],
    eligible_item_ids: frozenset[int] | None,
    enemy_threat_evidence: dict[int, dict[str, tuple[str, ...]]],
) -> tuple[list[dict[str, object]], list[QualifiedSituationalBranch]]:
    matchups, overlap_by_item, stability_by_scope = evidence
    asset_by_id = {
        integer(asset["id"]): asset
        for asset in assets
        if isinstance(asset.get("id"), int)
    }
    responses_by_item = {
        item_id: classify_item_threat_responses(asset)
        for item_id, asset in asset_by_id.items()
    }
    decision_cache: dict[tuple[int, int, str], tuple[str, str, str, str] | None] = {}
    candidates: list[dict[str, object]] = []
    qualified: list[QualifiedSituationalBranch] = []
    for row in matchups.iter_rows(named=True):
        item_id = integer(row["item_id"])
        if not _eligible_situational_item(
            item_id, excluded_item_ids, eligible_item_ids
        ):
            continue
        row_candidates, row_qualified = _matchup_candidates(
            row,
            asset_by_id=asset_by_id,
            responses_by_item=responses_by_item,
            overlap_by_item=overlap_by_item,
            stability_by_scope=stability_by_scope,
            enemy_threat_evidence=enemy_threat_evidence,
            decision_cache=decision_cache,
        )
        candidates.extend(row_candidates)
        qualified.extend(row_qualified)
    return candidates, qualified


def _candidate_gates(candidate: dict[str, object]) -> dict[str, object]:
    gates = object_dict(candidate.get("gates"))
    if gates is None:
        raise RuntimeError("situational candidate has no gate record")
    return gates


def _admit_situational_branches(
    qualified: list[QualifiedSituationalBranch],
) -> list[dict[str, object]]:
    ordered = sorted(
        qualified,
        key=lambda row: (
            tuple(-value for value in row[0]),
            str(row[2]["threat"]),
            integer(row[2]["enemy_hero_id"]),
            integer(row[2]["item_id"]),
        ),
    )
    branches: list[dict[str, object]] = []
    used_items: set[int] = set()
    used_guards: set[tuple[str, int, str, int, int]] = set()
    for _, candidate, branch in ordered:
        item_id = integer(branch["item_id"])
        guard = (
            str(branch["threat"]),
            integer(branch["enemy_hero_id"]),
            str(branch["enemy_scope"]),
            integer(branch["phase"]),
            integer(branch["tier"]),
        )
        if item_id in used_items or guard in used_guards:
            continue
        candidate["admitted"] = True
        branches.append(branch)
        used_items.add(item_id)
        used_guards.add(guard)
        if len(branches) == MAX_SITUATIONAL_BRANCHES:
            break
    return branches


def _situational_abstentions(
    candidate_count: int,
    branch_count: int,
) -> list[str]:
    rejected = candidate_count - branch_count
    if rejected:
        return [
            (
                f"{rejected} mechanics-backed candidate(s) failed at least one "
                "decision-copy, same-opportunity, comparator, support, overlap, "
                "bounded-uncertainty, or chronological-stability gate."
            )
        ]
    if not branch_count:
        return ["No mechanics-backed situational candidate was available."]
    return []


def _situational_policy(
    paths: RunPaths,
    hero_id: int,
    assets: list[dict[str, object]],
    *,
    excluded_item_ids: frozenset[int] = frozenset(),
    eligible_item_ids: frozenset[int] | None = None,
    comparator_item_ids: frozenset[int] | None = None,
    default_item_ids: tuple[int, ...] | None = None,
    graph: ItemGraph | None = None,
    priorities: dict[int, tuple[float, float, int]] | None = None,
    enemy_threat_evidence: dict[int, dict[str, tuple[str, ...]]] | None = None,
    con: duckdb.DuckDBPyConnection | None = None,
    preloaded_evidence: tuple[pl.DataFrame, pl.DataFrame] | None = None,
) -> dict[str, object]:
    candidates: list[dict[str, object]] = []
    qualified: list[QualifiedSituationalBranch] = []
    evidence = _load_situational_evidence(
        paths,
        hero_id,
        con,
        comparator_item_ids,
        preloaded_evidence,
    )
    if evidence is not None:
        candidates, qualified = _collect_situational_candidates(
            evidence,
            assets,
            excluded_item_ids,
            eligible_item_ids,
            enemy_threat_evidence or {},
        )
        if (
            default_item_ids is not None
            and graph is not None
            and priorities is not None
        ):
            for candidate in candidates:
                comparator_item_id = integer(
                    candidate.get("comparator_item_id"), default=0
                )
                replacement_legal = comparator_item_id > 0 and _replacement_is_legal(
                    default_item_ids,
                    comparator_item_id,
                    integer(candidate["item_id"]),
                    graph,
                    priorities,
                )
                _candidate_gates(candidate)["replacement_legality"] = replacement_legal
                candidate["qualified"] = bool(
                    candidate["qualified"] and replacement_legal
                )
            qualified = [
                row
                for row in qualified
                if bool(_candidate_gates(row[1]).get("replacement_legality"))
            ]
    branches = _admit_situational_branches(qualified)
    return {
        "version": SITUATIONAL_POLICY_VERSION,
        "threat_vocabulary": sorted(THREAT_CLASSES),
        "branches": branches,
        "candidate_audit": {
            "evaluated": len(candidates),
            "qualified": sum(bool(row["qualified"]) for row in candidates),
            "admitted": len(branches),
            "rejection_counts": dict(
                sorted(
                    Counter(
                        gate
                        for row in candidates
                        for gate, passed in _candidate_gates(row).items()
                        if not passed
                    ).items()
                )
            ),
            "sample": candidates[:32],
        },
        "abstentions": _situational_abstentions(len(candidates), len(branches)),
    }
