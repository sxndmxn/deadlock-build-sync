"""Save the complete discovery family before validation and verify it for reuse."""

import json
from hashlib import file_digest
from typing import cast

from deadlock_build_sync.artifacts import atomic_write_bytes, atomic_write_json
from deadlock_build_sync.build_evidence import METHOD_VERSION
from deadlock_build_sync.snapshot import sha256_json
from deadlock_build_sync.value_validation import (
    integer,
    object_dict,
    require_object_dict,
)

from .config import RunPaths
from .discovery_guide_groups import assign_guide_group_ids
from .discovery_types import FrozenHeroDiscovery


def calculate_discovery_source_identity(paths: RunPaths) -> dict[str, object]:
    hashes = {}
    for name in (
        "manifest.json",
        "raw/analysis.duckdb",
        "raw/heroes.json",
        "raw/items.json",
        "raw/items-all.json",
        "raw/ranks.json",
        "raw/patches.json",
    ):
        with (paths.run / name).open("rb") as source:
            hashes[name] = file_digest(source, "sha256").hexdigest()
    return {"schema_version": 1, "method_version": METHOD_VERSION, "files": hashes}


def require_discovery_source_identity(
    paths: RunPaths, expected: dict[str, object]
) -> None:
    if calculate_discovery_source_identity(paths) != expected:
        raise ValueError("Discovery source identity differs. Start a new --run-id.")


def save_discovery_snapshot(
    paths: RunPaths,
    frozen: dict[int, FrozenHeroDiscovery],
    groups: dict[int, dict[str, str]],
    source_identity: dict[str, object],
) -> None:
    require_discovery_source_identity(paths, source_identity)
    digest = sha256_json(frozen)
    atomic_write_bytes(
        paths.run / f"discovery-nominations-{digest[:16]}.json",
        json.dumps(frozen, allow_nan=False).encode(),
    )
    atomic_write_json(
        paths.run / f"guide-groups-{digest[:16]}.json",
        {
            "frozen_sha256": digest,
            "groups": groups,
            "source_identity": source_identity,
        },
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
    source_identity = object_dict(group_document.get("source_identity"))
    if source_identity is None:
        raise ValueError("Discovery has no source identity. Start a new --run-id.")
    require_discovery_source_identity(paths, source_identity)
    groups = {
        hero: assign_guide_group_ids(report["rows"]) for hero, report in frozen.items()
    }
    if group_document != {
        "frozen_sha256": digest,
        "groups": {str(hero): group for hero, group in groups.items()},
        "source_identity": source_identity,
    }:
        raise ValueError("Discovery snapshot guide groups do not match")
    return frozen, groups
