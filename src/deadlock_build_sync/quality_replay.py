"""Closed, deidentified inputs for later evaluation of a frozen policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .recommendation_state import (
    DecisionState,
    RecommendationAction,
    RecommendationError,
)
from .value_validation import object_dict, object_rows

if TYPE_CHECKING:
    from .policy import BuildPolicy


@dataclass(frozen=True)
class ReplayCase:
    policy_id: str
    match_group: str
    state: DecisionState
    observed_action: RecommendationAction
    observed_item_id: int | None
    core_completed: bool
    behind: bool
    ambiguous_purchase: bool


def _require_positive_integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise RecommendationError(f"replay has invalid {label}")
    return value


def _require_boolean_field(row: dict[str, object], key: str) -> bool:
    value = row.get(key)
    if not isinstance(value, bool):
        raise RecommendationError(f"replay requires boolean {key}")
    return value


def _parse_replay_case(
    row: dict[str, object], policy: BuildPolicy, cutoff: int
) -> ReplayCase:
    state = DecisionState.from_document(row.get("state"))
    if state.hero_id != policy.hero_id:
        raise RecommendationError("replay hero differs from frozen policy")
    start = _require_positive_integer(row.get("match_start_timestamp"), "match start")
    observed_at = _require_positive_integer(
        row.get("feature_as_of_timestamp"), "feature timestamp"
    )
    assigned_at = _require_positive_integer(
        row.get("policy_assigned_at"), "policy assignment"
    )
    if start <= cutoff:
        raise RecommendationError(
            "independent replay must start after the frozen cutoff"
        )
    if not start <= observed_at <= start + state.clock_s:
        raise RecommendationError("replay features are outside the pre-decision window")
    if not cutoff < assigned_at <= start:
        raise RecommendationError("replay policy must be assigned before the match")
    group = row.get("match_group")
    if not isinstance(group, str) or not group.strip():
        raise RecommendationError("replay lacks a deidentified match group")
    try:
        action = RecommendationAction(str(row.get("observed_action")))
    except ValueError as error:
        raise RecommendationError("replay has invalid observed action") from error
    if "observed_item_id" not in row:
        raise RecommendationError("replay requires observed_item_id, null for non-buys")
    item = row.get("observed_item_id")
    if action == RecommendationAction.BUY:
        item = _require_positive_integer(item, "observed item")
    elif item is not None:
        raise RecommendationError("only observed buys may name an item")
    return ReplayCase(
        policy.policy_id,
        group,
        state,
        action,
        item,
        _require_boolean_field(row, "core_completed"),
        _require_boolean_field(row, "behind"),
        _require_boolean_field(row, "ambiguous_purchase"),
    )


def parse_replay(
    document: object,
    policies: tuple[BuildPolicy, ...],
    *,
    cutoff: int,
    evidence_id: str,
) -> tuple[ReplayCase, ...]:
    """Reject reused, future-derived, duplicate, or cross-policy replay inputs.

    Returns:
        Cases retaining unfinished builds and ambiguous purchases for coverage audits.

    Raises:
        RecommendationError: If the replay violates its closed contract.

    """
    data = object_dict(document)
    if (
        data is None
        or type(data.get("schema_version")) is not int
        or data.get("schema_version") != 1
    ):
        raise RecommendationError("unsupported quality replay schema")
    if data.get("cohort_selection") != "all_eligible_player_matches":
        raise RecommendationError("replay must retain unfinished builds")
    raw_rows = data.get("cases")
    rows = object_rows(raw_rows)
    if rows is None or not isinstance(raw_rows, list) or len(rows) != len(raw_rows):
        raise RecommendationError("replay cases must be a list of objects")
    by_id = {policy.policy_id: policy for policy in policies}
    cases = []
    seen: set[tuple[str, str, int, int]] = set()
    for row in rows:
        policy = by_id.get(str(row.get("policy_id")))
        if policy is None:
            raise RecommendationError("replay references another frozen policy")
        case = _parse_replay_case(row, policy, cutoff)
        if case.state.build_evidence_id != evidence_id:
            raise RecommendationError("replay references another evidence artifact")
        key = (case.policy_id, case.match_group, case.state.hero_id, case.state.clock_s)
        if key in seen:
            raise RecommendationError("replay repeats a decision opportunity")
        seen.add(key)
        cases.append(case)
    return tuple(cases)
