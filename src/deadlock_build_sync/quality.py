"""Evaluate the shipped recommendation function without Steam or network access."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .mechanics import InventoryState, ItemGraph, MechanicsError, purchase_item
from .recommendation import recommend
from .recommendation_state import RecommendationAction, RecommendationError
from .snapshot import sha256_json

if TYPE_CHECKING:
    from .build_evidence import BuildEvidenceCatalog, HeroBuildEvidence
    from .policy import BuildPolicy
    from .quality_replay import ReplayCase
    from .recommendation_state import Recommendation

MINIMUM_REPLAY_MATCHES = 20


@dataclass(frozen=True)
class _Outcome:
    case: ReplayCase
    action: str
    agreement: bool
    baseline_agreement: bool
    illegal_buy: bool
    invalid_state: bool = False


@dataclass(frozen=True)
class _ReplayContext:
    catalog: BuildEvidenceCatalog
    policy: BuildPolicy
    evidence: HeroBuildEvidence
    assets: list[dict[str, object]]
    graph: ItemGraph


def _baseline_item(
    evidence: HeroBuildEvidence,
    case: ReplayCase,
    graph: ItemGraph,
) -> int | None:
    """Choose a training-popularity baseline within current mechanics.

    Returns:
        The most popular affordable legal item, or None for save.

    """
    inventory = InventoryState(case.state.owned_items, case.state.unlocked_flex_slots)
    for item in sorted(
        evidence.items,
        key=lambda item: (-item.training_adopter_matches, item.item_id),
    ):
        if item.training_adopter_matches < 20 or item.item_id in inventory.owned:
            continue
        try:
            purchase_item(graph, inventory, item.item_id)
            cost = graph.incremental_cash_cost(item.item_id, inventory.owned)
        except MechanicsError:
            continue
        if cost <= case.state.liquid_souls:
            return item.item_id
    return None


def _buy_is_illegal(
    decision: Recommendation, case: ReplayCase, graph: ItemGraph
) -> bool:
    if decision.item_id is None:
        return True
    inventory = InventoryState(case.state.owned_items, case.state.unlocked_flex_slots)
    try:
        purchase_item(graph, inventory, decision.item_id)
        cost = graph.incremental_cash_cost(decision.item_id, inventory.owned)
    except MechanicsError:
        return True
    return cost > case.state.liquid_souls or cost != decision.incremental_cost


def _evaluate_case(context: _ReplayContext, case: ReplayCase) -> _Outcome:
    try:
        decision = recommend(
            context.catalog, context.policy, case.state, context.assets
        )
    except (RecommendationError, MechanicsError):
        return _Outcome(
            case,
            "invalid",
            agreement=False,
            baseline_agreement=False,
            illegal_buy=False,
            invalid_state=True,
        )
    buy = decision.action == RecommendationAction.BUY
    illegal = buy and _buy_is_illegal(decision, case, context.graph)
    agreement = decision.action == case.observed_action and (
        not buy or decision.item_id == case.observed_item_id
    )
    baseline = _baseline_item(context.evidence, case, context.graph)
    baseline_agreement = (
        case.observed_action == RecommendationAction.SAVE
        if baseline is None
        else case.observed_action == RecommendationAction.BUY
        and baseline == case.observed_item_id
    )
    return _Outcome(case, decision.action.value, agreement, baseline_agreement, illegal)


def _summary(outcomes: list[_Outcome]) -> dict[str, object]:
    usable = [row for row in outcomes if not row.invalid_state]
    scored = [row for row in usable if not row.case.ambiguous_purchase]
    actions = Counter(row.action for row in usable)
    groups = {row.case.match_group for row in usable}
    return {
        "decisions": len(outcomes),
        "matches": len(groups),
        "invalid_states": sum(row.invalid_state for row in outcomes),
        "illegal_buys": sum(row.illegal_buy for row in outcomes),
        "actions": dict(sorted(actions.items())),
        "decision_coverage": (
            sum(actions[action] for action in ("buy", "save", "end")) / len(outcomes)
            if outcomes
            else None
        ),
        "affordable_buy_share": actions["buy"] / len(usable) if usable else None,
        "scored_decisions": len(scored),
        "ambiguous_decisions": len(usable) - len(scored),
        "top1_action_agreement": (
            sum(row.agreement for row in scored) / len(scored) if scored else None
        ),
        "training_popularity_top1": (
            sum(row.baseline_agreement for row in scored) / len(scored)
            if scored
            else None
        ),
    }


def _strata(
    outcomes: list[_Outcome], evidence: HeroBuildEvidence
) -> dict[str, list[_Outcome]]:
    default_path = (
        evidence.sequence_policy.default_path
        if evidence.sequence_policy is not None
        else ()
    )
    return {
        "opening": [row for row in outcomes if row.case.state.clock_s < 540],
        "midgame": [row for row in outcomes if 540 <= row.case.state.clock_s < 1200],
        "late": [row for row in outcomes if row.case.state.clock_s >= 1200],
        "behind": [row for row in outcomes if row.case.behind],
        "unfinished_core": [row for row in outcomes if not row.case.core_completed],
        "manual_deviation": [
            row
            for row in outcomes
            if not set(row.case.state.purchases) <= set(default_path)
        ],
    }


def _rank_summaries(outcomes: list[_Outcome]) -> dict[str, dict[str, object]]:
    ranks = sorted({row.case.state.average_badge // 10 for row in outcomes})
    return {
        str(rank): _summary([
            row for row in outcomes if row.case.state.average_badge // 10 == rank
        ])
        for rank in ranks
    }


def evaluate_policy(
    catalog: BuildEvidenceCatalog,
    policy: BuildPolicy,
    evidence: HeroBuildEvidence,
    cases: tuple[ReplayCase, ...],
    assets: list[dict[str, object]],
) -> dict[str, object]:
    """Replay the exact production policy and report observational diagnostics.

    Returns:
        Technical replay status and strata, never a causal outcome quality score.

    """
    graph = ItemGraph.from_assets(assets) if cases else None
    context = (
        _ReplayContext(catalog, policy, evidence, assets, graph)
        if graph is not None
        else None
    )
    outcomes = [
        _evaluate_case(context, case)
        for case in cases
        if case.policy_id == policy.policy_id and context is not None
    ]
    summary = _summary(outcomes)
    failed = any(row.illegal_buy or row.invalid_state for row in outcomes)
    strata = _strata(outcomes, evidence)
    supported = all(
        len({
            row.case.match_group
            for row in rows
            if row.action in {"buy", "save", "end"} and not row.case.ambiguous_purchase
        })
        >= MINIMUM_REPLAY_MATCHES
        for rows in strata.values()
    )
    return {
        "status": "fail" if failed else "pass" if supported else "unevaluated",
        "scope": "technical checks on exact runtime policy",
        "policy_id": policy.policy_id,
        "policy_sha256": sha256_json(policy.as_dict()),
        "minimum_matches": MINIMUM_REPLAY_MATCHES,
        "reason": (
            "invalid replay states or illegal buys"
            if failed
            else "technical replay checks passed; strategic superiority remains unproven"
            if supported
            else "insufficient independent replay matches in one or more required strata"
        ),
        "summary": summary,
        "strata": {name: _summary(rows) for name, rows in strata.items()},
        "rank_tiers": _rank_summaries(outcomes),
        "claim": "next-action imitation, coverage and legality; not item effect or win improvement",
    }
