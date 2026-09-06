"""Read selected build membership, never the hero-wide observed item table."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

import torch

from tools.comparisons.qdfm.extract import HEROES, fingerprint
from tools.comparisons.qdfm.state import Catalog

if TYPE_CHECKING:
    from pathlib import Path


def json_fingerprint(path: Path) -> str:
    document = json.loads(path.read_text(encoding="utf-8"))
    encoded = json.dumps(
        document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class BuildPool:
    hero_id: int
    path_id: str
    path_label: str
    core_targets: tuple[int, ...]
    core_path: tuple[int, ...]
    optional: dict[str, list[int]]
    branches: tuple[dict, ...]
    added_components: frozenset[int]
    item_ids: frozenset[int]

    def action_mask(self, actions: list[dict]) -> torch.Tensor:
        # A mixed basket must not smuggle an off-pool item through an allowed one.
        return torch.tensor(
            [
                bool(action["item_ids"]) and set(action["item_ids"]) <= self.item_ids
                for action in actions
            ],
            dtype=torch.bool,
        )

    def describe(self, catalog: Catalog) -> dict:
        return {
            "hero_id": self.hero_id,
            "hero": HEROES[self.hero_id][0],
            "path_id": self.path_id,
            "path_label": self.path_label,
            "core_target_ids": self.core_targets,
            "core_purchase_path_ids": self.core_path,
            "optional_item_ids_by_tier": self.optional,
            "added_required_component_ids": sorted(self.added_components),
            "items": [
                {"item_id": item, "name": catalog.names[item]}
                for item in sorted(self.item_ids)
            ],
            "situational_branches": self.branches,
            "situational_status": (
                "Branch items are already optional-tier members. Membership does not "
                "activate their triggers or assert their comparative advantage."
            ),
        }


def read_pool(hero: dict, build: dict, catalog: Catalog) -> BuildPool:
    core = tuple(build["core_policy"]["default_item_ids"])
    path = tuple(build["sequence_policy"]["component_expanded_default_path"])
    optional = build["tier_policy"]["item_ids_by_tier"]
    if not core or set(optional) != {"1", "2", "3", "4"}:
        raise ValueError("Incomplete selected build pool")
    optional_ids = {item for tier in optional.values() for item in tier}
    direct = set(path) | optional_ids
    if not set(core) <= direct <= set(catalog.ids):
        raise ValueError("Selected build refers to items outside the frozen catalog")
    expanded_core = set(core) | {
        child for item in core for child in catalog.ancestors[item]
    }
    if expanded_core != set(path) or len(path) != len(set(path)):
        raise ValueError("Core purchase path does not match its required components")
    # The current evidence admits no separate core alternatives. Future conditional
    # cards must not silently become unconditional items without trigger context.
    alternatives = build["core_policy"]["alternatives"]
    if any(row["item_id"] not in optional_ids for row in alternatives):
        raise ValueError(
            "Separate core alternatives require explicit applicability context"
        )
    branches = tuple(build["situational_policy"]["branches"])
    if any(row["item_id"] not in optional_ids for row in branches):
        raise ValueError(
            "Situational branch is absent from the selected optional tiers"
        )
    expanded = direct | {child for item in direct for child in catalog.ancestors[item]}
    return BuildPool(
        int(hero["hero_id"]),
        build["path_id"],
        build["path_label"],
        core,
        path,
        optional,
        branches,
        frozenset(expanded - direct),
        frozenset(expanded),
    )


def load_pools(evidence: Path, source: Path) -> tuple[list[BuildPool], dict]:
    document = json.loads(evidence.read_text(encoding="utf-8"))
    manifest = json.loads((source / "manifest.json").read_text())
    if document["schema_version"] != 9:
        raise ValueError("Unsupported build-evidence schema")
    if (
        document["client_version"] != manifest["sources"]["client_version"]
        or document["frozen_data_sha256"] != manifest["frozen_data_sha256"]
        or document["items_sha256"] != json_fingerprint(source / "raw/items-all.json")
        or document["heroes_sha256"] != json_fingerprint(source / "raw/heroes.json")
    ):
        raise ValueError("Build evidence and pilot source describe different snapshots")
    catalog = Catalog(source)
    pools = [
        read_pool(hero, build, catalog)
        for hero in document["heroes"]
        if int(hero["hero_id"]) in HEROES
        for build in hero["builds"]
    ]
    keys = {(pool.hero_id, pool.path_id) for pool in pools}
    if len(keys) != len(pools) or {pool.hero_id for pool in pools} != set(HEROES):
        raise ValueError("Missing or duplicate build pools for the nine pilot heroes")
    return pools, {
        "evidence_path": str(evidence.resolve()),
        "evidence_sha256": fingerprint(evidence),
        "evidence_artifact_id": document["artifact_id"],
        "client_version": document["client_version"],
        "source_manifest_sha256": fingerprint(source / "manifest.json"),
        "catalog_sha256": fingerprint(source / "raw/items.json"),
        "pools": [pool.describe(catalog) for pool in pools],
    }
