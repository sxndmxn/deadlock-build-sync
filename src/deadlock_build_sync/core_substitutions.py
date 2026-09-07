"""A core substitution carries its own frozen core admission evidence."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .artifacts import ArtifactError
from .build_evidence_discovery import validate_discovery
from .build_evidence_values import _required_int
from .purchase_planner import plan_purchases
from .value_validation import object_dict, object_list

if TYPE_CHECKING:
    from .match_choices import AutomaticBranch
    from .mechanics import ItemGraph


def validate_substitution_routes(
    graph: ItemGraph, branches: tuple[AutomaticBranch, ...], core: tuple[int, ...]
) -> None:
    for branch in branches:
        if not branch.substituted_core:
            continue
        if not branch.substitution_evidence:
            raise ArtifactError("Core substitution lacks its separate evidence record")
        plan = plan_purchases(
            graph, branch.substituted_path, branch.substituted_core, {}
        )
        valid = (
            set(core) - set(branch.substituted_core) == {branch.comparator_item_id}
            and set(branch.substituted_core) - set(core) == {branch.item_id}
            and tuple(step.item_id for step in plan.actions) == branch.substituted_path
            and set(plan.final_inventory) == set(branch.substituted_core)
        )
        if not valid:
            raise ArtifactError(
                "Core substitution has an invalid component path or final inventory"
            )


def parse_substitution(
    value: object, path: tuple[int, ...], item: int, checkpoint: int
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    if value is None:
        return (), ()
    row = object_dict(value)
    if row is None:
        raise ArtifactError("Core substitution is malformed")
    raw_core, raw_path = object_list(row.get("core")), object_list(row.get("path"))
    discovery = object_dict(row.get("discovery"))
    if raw_core is None or raw_path is None or discovery is None:
        raise ArtifactError("Core substitution lacks separate admission evidence")
    core = tuple(
        _required_int(value, "substituted core item", minimum=1) for value in raw_core
    )
    route = tuple(
        _required_int(value, "substituted path item", minimum=1) for value in raw_path
    )
    expected = (*path[:checkpoint], item, *path[checkpoint + 1 :])
    if (
        route != expected
        or item not in core
        or row.get("source_identity_id") != discovery.get("identity_id")
    ):
        raise ArtifactError("Core substitution differs from its admitted purchase path")
    validate_discovery(discovery, core, route)
    if discovery.get("evidence_status") != "outcome_supported":
        raise ArtifactError("Core substitution lacks supported outcome evidence")
    return core, route
