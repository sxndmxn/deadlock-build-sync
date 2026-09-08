from __future__ import annotations

from collections import Counter

from .ability_order import AbilityPath
from .artifact_bundle_types import (
    ArtifactBundleError,
)
from .policy import BuildPolicy, NodeKind
from .value_validation import integer, object_dict, object_list, object_rows


def _ability_projection(
    raw: dict[str, object], policy: BuildPolicy
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    steps = object_rows(raw.get("steps"))
    if steps is None or len(steps) != 16:
        raise ArtifactBundleError(
            f"hero {policy.hero_id} ability policy must contain 16 actions"
        )
    ability_ids: list[int] = []
    decision_support: list[int] = []
    for step in steps:
        ability_id = step.get("ability_id")
        support = step.get("decision_reached_support")
        if (
            not isinstance(ability_id, int)
            or not isinstance(support, int)
            or support <= 0
        ):
            raise ArtifactBundleError(
                f"hero {policy.hero_id} has a malformed ability action"
            )
        ability_ids.append(ability_id)
        decision_support.append(support)
    if len(Counter(ability_ids)) != 4 or any(
        count != 4 for count in Counter(ability_ids).values()
    ):
        raise ArtifactBundleError(
            f"hero {policy.hero_id} ability policy is not a complete four-rank path"
        )
    policy_abilities = tuple(
        node.ability_id
        for node in policy.ability_plan
        if node.kind == NodeKind.ABILITY and node.ability_id is not None
    )
    if tuple(ability_ids) != policy_abilities:
        raise ArtifactBundleError(
            f"hero {policy.hero_id} ability projection differs from its policy"
        )
    return tuple(ability_ids), tuple(decision_support)


def _ability_path(hero: dict[str, object], policy: BuildPolicy) -> AbilityPath:
    raw = object_dict(hero.get("ability_policy"))
    if raw is None or object_list(raw.get("steps")) is None:
        raise ArtifactBundleError(f"hero {policy.hero_id} has no ability policy")
    ability_ids, decision_support = _ability_projection(raw, policy)
    integer_fields = (
        "all_valid_telemetry_appearances",
        "complete_path_appearances",
        "final_branch_support",
    )
    if any(not isinstance(raw.get(field), int) for field in integer_fields):
        raise ArtifactBundleError(
            f"hero {policy.hero_id} ability policy has invalid support"
        )
    cohort_matches = integer(raw["all_valid_telemetry_appearances"])
    complete_matches = integer(raw["complete_path_appearances"])
    matches = integer(raw["final_branch_support"])
    rate = raw.get("observed_final_branch_outcome_rate")
    if cohort_matches <= 0 or complete_matches <= 0 or matches <= 0:
        raise ArtifactBundleError(
            f"hero {policy.hero_id} ability policy has incoherent support"
        )
    if matches > complete_matches or complete_matches > cohort_matches:
        raise ArtifactBundleError(
            f"hero {policy.hero_id} ability policy has incoherent support"
        )
    if not isinstance(rate, (int, float)) or not 0.0 <= float(rate) <= 1.0:
        raise ArtifactBundleError(
            f"hero {policy.hero_id} ability policy has incoherent support"
        )
    wins = round(float(rate) * matches)
    quality = object_dict(raw.get("quality"))
    fallback_reason = quality.get("fallback_reason") if quality is not None else None
    path = AbilityPath(
        ability_ids=ability_ids,
        matches=matches,
        wins=wins,
        losses=matches - wins,
        cohort_matches=cohort_matches,
        complete_path_matches=complete_matches,
        decision_support=decision_support,
        selection=str(raw.get("selection") or "MOST_SUPPORTED_LEGAL_STATE"),
        filter_item_ids=tuple(
            item_id
            for item_id in object_list(raw.get("filter_item_ids")) or []
            if isinstance(item_id, int)
        ),
        fallback_reason=fallback_reason if isinstance(fallback_reason, str) else None,
    )
    if quality != path.quality_assessment():
        raise ArtifactBundleError(
            "ability quality assessment differs from its evidence"
        )
    return path
