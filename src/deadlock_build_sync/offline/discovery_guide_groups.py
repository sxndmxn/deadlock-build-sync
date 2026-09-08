"""Group frozen exact-core variants for publication without reading outcomes."""

from operator import itemgetter

from .discovery_grouping import group_core_candidates
from .discovery_types import CoreDiscoveryCandidate, NominatedCoreBuild


def assign_guide_group_ids(nominations: list[NominatedCoreBuild]) -> dict[str, str]:
    rows = sorted(nominations, key=lambda row: tuple(sorted(row["items"])))
    candidates: list[CoreDiscoveryCandidate] = list(rows)
    grouping = group_core_candidates(candidates)
    result: dict[str, str] = {}
    for indices in grouping["groups"]:
        members = [rows[index] for index in indices]
        default = min(members, key=itemgetter("selection_rank"))["identity_id"]
        result.update((member["identity_id"], default) for member in members)
    return result
