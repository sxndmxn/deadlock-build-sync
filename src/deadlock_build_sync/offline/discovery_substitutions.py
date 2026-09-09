"""Freeze single-step core substitutions between separately nominated identities."""

from deadlock_build_sync.mechanics import ItemGraph
from deadlock_build_sync.value_validation import object_dict

from .decision_rows import DecisionRows
from .discovery_admission import build_discovery_record
from .discovery_branches import freeze_choice_conditions
from .discovery_types import NominatedCoreBuild


def freeze_substitutions(
    rows: DecisionRows, nominees: list[NominatedCoreBuild], graph: ItemGraph
) -> None:
    for base in nominees:
        if not base["guide"]["ready"]:
            continue
        pool = {item for items in base["guide"]["pool"].values() for item in items}
        for alternative in nominees:
            checkpoint = _find_substitution_checkpoint(base, alternative, pool)
            if checkpoint is None:
                continue
            route = alternative["guide"]["path"]
            item = route[checkpoint]
            for candidate in freeze_choice_conditions(
                rows, base, item, checkpoint, graph
            ):
                base["branch_candidates"].append({
                    **candidate,
                    "substitution": {
                        "source_identity_id": alternative["identity_id"],
                        "core": alternative["path"]["order"],
                        "path": route,
                    },
                })


def select_validated_branch_candidates(
    base: NominatedCoreBuild, reviewed: list[NominatedCoreBuild]
) -> list[dict[str, object]]:
    admitted = {
        row["identity_id"]: row
        for row in reviewed
        if not row["rejections"] and row["evidence_status"] == "outcome_supported"
    }
    result = []
    for candidate in base["branch_candidates"]:
        substitution = object_dict(candidate.get("substitution"))
        if substitution is None:
            result.append(candidate)
        elif str(substitution["source_identity_id"]) in admitted:
            source = admitted[str(substitution["source_identity_id"])]
            result.append({
                **candidate,
                "substitution": {
                    **substitution,
                    "discovery": build_discovery_record(source),
                },
            })
    return result


def _find_substitution_checkpoint(
    base: NominatedCoreBuild, alternative: NominatedCoreBuild, pool: set[int]
) -> int | None:
    if not alternative["guide"]["ready"] or alternative is base:
        return None
    path, route = base["guide"]["path"], alternative["guide"]["path"]
    if len(route) != len(path):
        return None
    changed = [index for index, item in enumerate(path) if item != route[index]]
    if len(changed) != 1 or len(set(base["items"]) - set(alternative["items"])) != 1:
        return None
    checkpoint = changed[0]
    item = route[checkpoint]
    return (
        checkpoint
        if item in pool
        and item in alternative["items"]
        and path[checkpoint] in base["items"]
        else None
    )
