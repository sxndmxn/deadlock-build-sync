"""Save the complete discovery family before validation and verify it for reuse."""

import json
from typing import cast

from deadlock_build_sync.snapshot import sha256_json
from deadlock_build_sync.value_validation import integer, require_object_dict

from .config import RunPaths
from .discovery_guide_groups import assign_guide_group_ids
from .discovery_types import FrozenHeroDiscovery


def save_discovery_snapshot(
    paths: RunPaths,
    frozen: dict[int, FrozenHeroDiscovery],
    groups: dict[int, dict[str, str]],
) -> None:
    digest = sha256_json(frozen)
    (paths.run / f"discovery-nominations-{digest[:16]}.json").write_text(
        json.dumps(frozen, allow_nan=False), encoding="utf-8"
    )
    (paths.run / f"guide-groups-{digest[:16]}.json").write_text(
        json.dumps({"frozen_sha256": digest, "groups": groups}), encoding="utf-8"
    )


def load_discovery_snapshot(
    paths: RunPaths, heroes: list[dict[str, object]]
) -> tuple[dict[int, FrozenHeroDiscovery], dict[int, dict[str, str]]]:
    candidates = list(paths.run.glob("discovery-nominations-*.json"))
    if len(candidates) != 1:
        raise ValueError("Resume requires one complete discovery snapshot")
    document = require_object_dict(
        json.loads(candidates[0].read_text(encoding="utf-8"))
    )
    frozen = {
        integer(hero): cast("FrozenHeroDiscovery", require_object_dict(record))
        for hero, record in document.items()
    }
    if set(frozen) != {integer(hero["id"]) for hero in heroes}:
        raise ValueError("Discovery snapshot does not cover the requested heroes")
    digest = sha256_json(frozen)
    if candidates[0].name != f"discovery-nominations-{digest[:16]}.json":
        raise ValueError("Discovery snapshot fingerprint does not match")
    groups_path = paths.run / f"guide-groups-{digest[:16]}.json"
    group_document = require_object_dict(
        json.loads(groups_path.read_text(encoding="utf-8"))
    )
    groups = {
        hero: assign_guide_group_ids(report["rows"]) for hero, report in frozen.items()
    }
    if group_document != {
        "frozen_sha256": digest,
        "groups": {str(hero): group for hero, group in groups.items()},
    }:
        raise ValueError("Discovery snapshot guide groups do not match")
    return frozen, groups
