"""Join the discovered core to a complete pool and explicit purchase decisions."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from deadlock_build_sync.mechanics import MechanicsError

from experiments.build_guides.decisions import attach_decisions
from experiments.build_guides.evidence import MAX_PER_TIER, MIN_BUYERS, placement
from experiments.build_guides.paths import default_path, plan
from experiments.build_guides.purposes import primary_text, purpose

if TYPE_CHECKING:
    from deadlock_build_sync.mechanics import ItemGraph


def mechanics(asset: dict) -> str:
    description = primary_text(asset)
    properties = asset.get("properties", {})
    names = []
    for section in asset.get("tooltip_sections", []):
        for attributes in section.get("section_attributes", []):
            for key in ("important_properties", "elevated_properties", "properties"):
                names.extend(attributes.get(key, []))
    stats = []
    for name in dict.fromkeys(names):
        value = properties.get(name, {})
        label = value.get("label") or value.get("postvalue_label")
        amount = value.get("value")
        if label and amount not in {None, "0", "-1", ""}:
            suffix = value.get("postfix", "")
            rendered = str(amount)
            if suffix and not rendered.endswith(suffix):
                rendered += suffix
            stats.append(f"{rendered} {label}")
    return "; ".join(filter(None, [description, ", ".join(stats[:4])]))


def item_pool(graph: ItemGraph, evidence: dict, core_path: list[int]) -> dict:
    ranked = sorted(
        (
            item
            for item, stats in evidence["items"].items()
            if item in graph.nodes
            and 1 <= graph.require(item).tier <= 4
            and item not in core_path
            and stats["buyers"] >= MIN_BUYERS
        ),
        key=lambda item: (-evidence["items"][item]["buyers"], item),
    )
    result = {}
    for tier in range(1, 5):
        selected = [item for item in ranked if graph.require(item).tier == tier][
            :MAX_PER_TIER
        ]
        result[str(tier)] = sorted(
            selected,
            key=lambda item: (
                evidence["items"][item]["time_seconds_q25_q50_q75"][1],
                item,
            ),
        )
    return result


def card_for(
    item: int, guide: dict, evidence: dict, graph: ItemGraph, assets: dict
) -> dict:
    path = [action["item_id"] for action in guide["default_path"]["actions"]]
    ancestors = graph.transitive_components(item)
    upgrades = [core for core in guide["core_ids"] if core in ancestors]
    position = placement(item, path, evidence)
    earliest = max(
        (path.index(core) + 1 for core in upgrades if core in path), default=0
    )
    position["minimum_after_step"] = earliest
    if position["after_step"] is not None and position["after_step"] < earliest:
        position["after_step"] = None
        position["supported"] = False
        position["basis"] = (
            "Timing unknown; observed position precedes a required core item"
        )
    summary = mechanics(assets[item])
    return {
        "item_id": item,
        "name": graph.require(item).name,
        "tier": graph.require(item).tier,
        "catalog_cost": graph.require(item).cost,
        "active": graph.require(item).active,
        "components": list(graph.components[item]),
        "ancestors": list(ancestors),
        "upgrades_core": upgrades,
        "placement": position,
        "purchase_evidence": evidence["items"][item],
        "mechanics": summary or "No concise mechanic description in the pinned asset",
        "mechanics_ref": f"raw/items.json#{item}",
        **purpose(assets[item]),
        "evidence_kind": "mechanics-based choice; observed adoption and placement",
        "passes_conditional_outcome_gate": False,
        "skip": "Continue the default path if this need is absent; save if unaffordable",
    }


def attach_branch(card: dict, guide: dict, graph: ItemGraph) -> None:
    try:
        branch = plan(graph, guide, [card["item_id"]])
    except (MechanicsError, ValueError) as error:
        card["branch"] = None
        card["blocked_reason"] = str(error)
        return
    baseline = guide["default_path"]["actions"]
    index = card["placement"]["after_step"]
    next_item = baseline[index]["item_id"] if index < len(baseline) else None
    card["branch"] = branch
    card["blocked_reason"] = None
    card["extra_path_cost"] = branch["remaining_cost"] - baseline[-1]["cumulative_cost"]
    card["delays_item"] = next_item
    card["resume_path"] = [step["item_id"] for step in baseline[index:]]
    card["rebought_components"] = [
        item
        for item, count in Counter(
            step["item_id"] for step in branch["actions"]
        ).items()
        if count > 1
    ]


def assemble(row: dict, graph: ItemGraph, assets: dict, evidence: dict) -> dict:
    default = default_path(row, graph, evidence)
    path = [action["item_id"] for action in default["actions"]]
    reserved = set(path) | set(row["items"])
    for item in row["items"]:
        reserved.update(graph.transitive_components(item))
    pool = item_pool(graph, evidence, list(reserved))
    guide = {
        "schema_version": 2,
        "hero_id": row["hero_id"],
        "hero": row["hero"],
        "identity_id": row["identity_id"],
        "arm": row["arm"],
        "core_ids": row["items"],
        "core_names": row["names"],
        "core_validation": row["core_validation"],
        "passes_core_gate": row["passes_core_gate"],
        "passes_identity_gate": row["passes_identity_gate"],
        "passes_sequence_gate": row["passes_sequence_gate"],
        "rejections": row["preview_rejections"],
        "default_path": default,
        "item_pool": pool,
        "discovery_owners": evidence["population"],
        "pool_policy": {"minimum_buyers": MIN_BUYERS, "maximum_per_tier": MAX_PER_TIER},
        "choices": [],
        "core_path_supported": bool(row["complete_preview"] and default["ready"]),
        "full_policy_validated": False,
        "production_promotion": False,
    }
    guide["choices"] = [
        card_for(item, guide, evidence, graph, assets)
        for items in pool.values()
        for item in items
    ]
    for card in guide["choices"]:
        attach_branch(card, guide, graph)
    attach_decisions(guide, graph)
    guide["catalog"] = {
        str(item): {
            "name": node.name,
            "cost": node.cost,
            "tier": node.tier,
            "active": node.active,
            "components": list(graph.components[item]),
        }
        for item, node in graph.nodes.items()
    }
    return guide
