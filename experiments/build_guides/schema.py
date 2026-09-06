"""Verify saved guides and adapt legacy presentation without changing artifacts."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from deadlock_build_sync.mechanics import ItemGraph

from experiments.build_guides.assemble import attach_branch, mechanics
from experiments.build_guides.decisions import attach_decisions
from experiments.build_guides.purposes import purpose
from experiments.identity_paths.storage import read_json
from experiments.qdfm.extract import fingerprint


def adapt_legacy(original: dict, graph: ItemGraph, assets: dict) -> dict:
    guide = deepcopy(original)
    if type(guide.get("schema_version")) is not int or guide["schema_version"] not in {
        1,
        2,
    }:
        raise ValueError("Unsupported guide schema version")
    if guide["schema_version"] == 2:
        return guide
    guide["schema_version"] = 2
    guide["source_schema_version"] = 1
    path = [step["item_id"] for step in guide["default_path"]["actions"]]
    for card in guide["choices"]:
        position = card["placement"]
        earliest = max(
            (path.index(item) + 1 for item in card["upgrades_core"] if item in path),
            default=0,
        )
        position["minimum_after_step"] = earliest
        if not position["supported"] or not path or position["after_step"] < earliest:
            position["after_step"] = None
            position["supported"] = False
            position["basis"] = "Timing unknown; legacy placement was unsupported"
        card.update(purpose(assets[card["item_id"]]))
        card["mechanics"] = mechanics(assets[card["item_id"]])
        for key in (
            "branch",
            "blocked_reason",
            "extra_path_cost",
            "delays_item",
            "resume_path",
            "rebought_components",
        ):
            card.pop(key, None)
    for card in guide["choices"]:
        attach_branch(card, guide, graph)
    attach_decisions(guide, graph)
    return guide


def load_guide(path: Path) -> tuple[dict, ItemGraph]:
    manifest = read_json(path.parent / "manifest.json")
    if manifest["files"].get(path.name) != fingerprint(path):
        raise ValueError("Guide changed after generation")
    guide = read_json(path)
    source = Path(guide["catalog_source"]["path"])
    if fingerprint(source) != guide["catalog_source"]["sha256"]:
        raise ValueError("Item catalog changed after guide generation")
    assets = read_json(source)
    graph = ItemGraph.from_assets(assets)
    return adapt_legacy(guide, graph, {asset["id"]: asset for asset in assets}), graph
