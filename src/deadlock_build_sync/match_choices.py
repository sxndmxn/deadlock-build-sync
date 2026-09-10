"""Typed automatic branches and strictly pre-decision match observations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .artifacts import ArtifactError
from .branch_evidence import validate_branch_diagnostics
from .core_substitutions import parse_substitution
from .value_validation import object_dict, object_list

if TYPE_CHECKING:
    from .purchase_guidance_types import PurchasePlan
    from .recommendation_state import DecisionState


@dataclass(frozen=True)
class MatchEconomy:
    personal_net_worth: int | None
    lobby_net_worths: tuple[int, ...]
    observed_at_s: int | None

    def relative_wealth(self, clock_s: int) -> float | None:
        if (
            self.personal_net_worth is None
            or len(self.lobby_net_worths) != 12
            or self.observed_at_s is None
            or not 0 < clock_s - self.observed_at_s <= 300
            or sum(self.lobby_net_worths) <= 0
        ):
            return None
        return self.personal_net_worth * 12 / sum(self.lobby_net_worths)


@dataclass(frozen=True)
class AutomaticBranch:
    item_id: int
    after_step: int
    condition: str
    value: str | int
    lower_bound: float
    support: int
    comparator_item_id: int
    evidence: dict[str, object]
    substituted_core: tuple[int, ...] = ()
    substituted_path: tuple[int, ...] = ()
    substitution_evidence: dict[str, object] = field(default_factory=dict)
    default_plan: PurchasePlan | None = None

    def matches(self, state: DecisionState) -> bool:
        if self.condition == "relative_wealth":
            ratio = (
                state.economy.relative_wealth(state.clock_s) if state.economy else None
            )
            if ratio is None:
                return False
            return (
                (self.value == "behind" and ratio < 0.90)
                or (self.value == "ahead" and ratio > 1.10)
                or (self.value == "even" and 0.90 <= ratio <= 1.10)
            )
        if (
            state.enemy_observed_at_s is None
            or not 0 < state.clock_s - state.enemy_observed_at_s <= 300
        ):
            return False
        observations = (
            state.enemy_hero_ids
            if self.condition == "enemy_hero"
            else state.enemy_item_ids
        )
        return self.value in observations


def parse_automatic_branches(
    value: object, pool: set[int], path: tuple[int, ...]
) -> tuple[AutomaticBranch, ...]:
    if value is None:
        return ()
    document = object_dict(value)
    rows = object_list(document.get("branches")) if document else None
    if document is None or document.get("version") != 1 or rows is None:
        raise ArtifactError("Automatic choice evidence has an invalid contract")
    branches = []
    identities = set()
    for raw in rows:
        branch = _parse_branch(raw, pool, path)
        identity = (
            branch.item_id,
            branch.after_step,
            branch.condition,
            branch.value,
            branch.substituted_core,
        )
        if identity in identities:
            raise ArtifactError("Automatic choice evidence contains duplicate branches")
        identities.add(identity)
        branches.append(branch)
    return tuple(branches)


def _parse_branch(
    value: object, pool: set[int], path: tuple[int, ...]
) -> AutomaticBranch:
    row = object_dict(value)
    if row is None:
        raise ArtifactError("Automatic choice evidence has a malformed branch")
    item, checkpoint = row.get("item_id"), row.get("after_step")
    condition, trigger = row.get("condition"), row.get("value")
    comparator, support, lower = (
        row.get("comparator_item_id"),
        row.get("support"),
        row.get("lower_bound"),
    )
    evidence = object_dict(row.get("evidence"))
    if (
        type(item) is not int
        or item not in pool
        or type(checkpoint) is not int
        or not 0 <= checkpoint < len(path)
        or comparator != path[checkpoint]
        or type(support) is not int
        or support < 40
        or not isinstance(lower, (int, float))
        or isinstance(lower, bool)
        or not 0 < lower <= 1
        or evidence is None
    ):
        raise ArtifactError("Automatic choice identity or support is invalid")
    _validate_condition(condition, trigger)
    _validate_gates(evidence)
    if (
        evidence.get("test_evaluated") is not False
        or evidence.get("lower_bound") != lower
    ):
        raise ArtifactError("Automatic choice has incompatible outcome evidence")
    if not isinstance(trigger, (str, int)) or type(comparator) is not int:
        raise ArtifactError("Automatic choice trigger or comparator is invalid")
    validate_branch_diagnostics(evidence, support, float(lower))
    core, route = parse_substitution(row.get("substitution"), path, item, checkpoint)
    return AutomaticBranch(
        item,
        checkpoint,
        str(condition),
        trigger,
        float(lower),
        support,
        comparator,
        evidence,
        core,
        route,
        object_dict(row.get("substitution")) or {},
    )


def _validate_gates(evidence: dict[str, object]) -> None:
    gates = object_dict(evidence.get("gates"))
    expected = {
        "support",
        "overlap",
        "balance",
        "uncertainty",
        "temporal_stability",
        "corrected_outcome",
        "legal_path",
        "pre_decision_cohort",
    }
    if (
        gates is None
        or set(gates) != expected
        or any(passed is not True for passed in gates.values())
    ):
        raise ArtifactError("Automatic choice did not pass all admission gates")


def _validate_condition(condition: object, trigger: object) -> None:
    if not isinstance(condition, str) or condition not in {
        "relative_wealth",
        "enemy_hero",
        "enemy_item",
    }:
        raise ArtifactError("Automatic choice condition is unknown")
    if (
        condition == "relative_wealth"
        and (not isinstance(trigger, str) or trigger not in {"behind", "even", "ahead"})
    ) or (
        condition != "relative_wealth" and (type(trigger) is not int or trigger <= 0)
    ):
        raise ArtifactError("Automatic choice trigger is invalid")
