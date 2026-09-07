"""Group frozen exact-core variants for publication without reading outcomes."""

from operator import itemgetter

from .discovery_grouping import consolidate
from .discovery_types import Candidate, Nomination


def guide_group_ids(nominations: list[Nomination]) -> dict[str, str]:
    rows = sorted(nominations, key=lambda row: tuple(sorted(row["items"])))
    candidates: list[Candidate] = list(rows)
    grouping = consolidate(candidates)
    result: dict[str, str] = {}
    for indices in grouping["groups"]:
        members = [rows[index] for index in indices]
        default = min(members, key=itemgetter("selection_rank"))["identity_id"]
        result.update((member["identity_id"], default) for member in members)
    return result
