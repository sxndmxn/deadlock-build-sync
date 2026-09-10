"""Compare frozen cores, supported orders, and complete rendered guides."""

from __future__ import annotations

import argparse
import json
from itertools import combinations
from pathlib import Path

from deadlock_build_sync.artifacts import atomic_write_bytes, atomic_write_json
from deadlock_build_sync.build_support import numeric
from deadlock_build_sync.purchase_windows import wilson_score_interval
from deadlock_build_sync.value_validation import (
    integer,
    object_dict,
    require_object_dict,
    require_object_list,
    require_object_rows,
)

MODES = ("current", "beam-order", "beam")


def read_document(path: Path) -> dict[str, object]:
    return require_object_dict(json.loads(path.read_text(encoding="utf-8")))


def describe_build(
    build: dict[str, object], names: dict[int, str]
) -> dict[str, object]:
    discovery = require_object_dict(build["discovery"])
    validation = require_object_dict(discovery["validation"])
    core = [
        integer(item)
        for item in require_object_list(
            require_object_dict(build["core_policy"])["default_item_ids"]
        )
    ]
    path = [
        integer(item)
        for item in require_object_list(
            require_object_dict(build["sequence_policy"])[
                "component_expanded_default_path"
            ]
        )
    ]
    owners, wins = integer(validation["owners"]), integer(validation["wins"])
    lower, upper = wilson_score_interval(wins, owners)
    return {
        "core": core,
        "core_names": [names[item] for item in core],
        "path": path,
        "path_names": [names[item] for item in path],
        "core_cost": discovery["cost"],
        "generator": build.get("generator", {"effective": "current"}),
        "owners": owners,
        "wins": wins,
        "win_rate": validation["win_rate"],
        "lower_95": lower,
        "upper_95": upper,
        "hero_win_rate": validation["hero_win_rate"],
        "hero_matches": validation["rows"],
        "coverage": validation["coverage"],
        "order_support": discovery["order_validation"],
        "discovery_order_support": require_object_dict(discovery["path"])["discovery"],
        "selection_order_support": require_object_dict(discovery["path"])["selection"],
        "status": discovery["evidence_status"],
        "limitations": discovery["evidence_limitations"],
        "tier_pool": require_object_dict(build["tier_policy"])["item_ids_by_tier"],
    }


def compare_groups(
    documents: dict[str, dict[str, object]], names: dict[int, str]
) -> list[dict[str, object]]:
    heroes = {
        mode: {
            integer(row["hero_id"]): row
            for row in require_object_rows(document["heroes"])
        }
        for mode, document in documents.items()
    }
    rows: list[dict[str, object]] = []
    for hero_id, baseline in heroes["current"].items():
        by_mode = {
            mode: require_object_rows(heroes[mode][hero_id]["builds"]) for mode in MODES
        }
        groups = list(
            dict.fromkeys(str(build["guide_group_id"]) for build in by_mode["current"])
        )
        for index, group in enumerate(groups, 1):
            row: dict[str, object] = {
                "hero": baseline["hero"],
                "hero_id": hero_id,
                "group": group,
                "number": index,
            }
            for mode, builds in by_mode.items():
                row[mode] = describe_group(builds, group, names)
            rows.append(row)
    return rows


def describe_group(
    builds: list[dict[str, object]], group: str, names: dict[int, str]
) -> dict[str, object]:
    members = [build for build in builds if build["guide_group_id"] == group]
    default = next(build for build in members if build["path_id"] == group)
    return {
        **describe_build(default, names),
        "variant_count": len(members),
        "variants": [describe_build(build, names) for build in members],
    }


def comparison_totals(rows: list[dict[str, object]]) -> dict[str, object]:
    summary: dict[str, object] = {
        "groups": len(rows),
        "heroes": len({row["hero_id"] for row in rows}),
    }
    for mode in MODES:
        builds = [require_object_dict(row[mode]) for row in rows]
        pairs = [
            (require_object_dict(row["current"]), require_object_dict(row[mode]))
            for row in rows
        ]
        summary[mode] = mode_totals(builds, pairs)
    original = {
        (row["hero_id"], tuple(sorted(require_object_list(variant["core"]))))
        for row in rows
        for variant in require_object_rows(
            require_object_dict(row["current"])["variants"]
        )
    }
    summary["new_beam_cores"] = sum(
        (row["hero_id"], tuple(sorted(require_object_list(variant["core"]))))
        not in original
        for row in rows
        for variant in require_object_rows(require_object_dict(row["beam"])["variants"])
    )
    return summary


def mode_totals(
    builds: list[dict[str, object]],
    pairs: list[tuple[dict[str, object], dict[str, object]]],
) -> dict[str, object]:
    return {
        "variants": sum(integer(build["variant_count"]) for build in builds),
        "beam_defaults": sum(
            require_object_dict(build["generator"])["effective"] == "beam"
            for build in builds
        ),
        "same_default_core": sum(
            set(require_object_list(old["core"]))
            == set(require_object_list(new["core"]))
            for old, new in pairs
        ),
        "same_final_core_order": sum(old["core"] == new["core"] for old, new in pairs),
        "same_component_path": sum(old["path"] == new["path"] for old, new in pairs),
        "outcome_supported_defaults": sum(
            build["status"] == "outcome_supported" for build in builds
        ),
        "mean_default_cost": sum(integer(build["core_cost"]) for build in builds)
        / len(builds),
        "beam_variants": sum(
            require_object_dict(variant["generator"])["effective"] == "beam"
            for build in builds
            for variant in require_object_rows(build["variants"])
        ),
        "mean_within_group_core_distance": sum(
            group_core_distance(build) for build in builds
        )
        / len(builds),
    }


def group_core_distance(build: dict[str, object]) -> float:
    cores = [
        frozenset(integer(item) for item in require_object_list(variant["core"]))
        for variant in require_object_rows(build["variants"])
    ]
    distances = [
        1 - len(left & right) / max(1, len(left | right))
        for left, right in combinations(cores, 2)
    ]
    return sum(distances) / len(distances) if distances else 0.0


def build_lines(label: str, build: dict[str, object]) -> list[str]:
    metadata = require_object_dict(build["generator"])
    order = require_object_dict(build["order_support"])
    return [
        f"**{label}**",
        "",
        "Core: "
        + " · ".join(str(item) for item in require_object_list(build["core_names"])),
        "",
        "Buy: "
        + " → ".join(str(item) for item in require_object_list(build["path_names"])),
        "",
        f"Cost: {integer(build['core_cost']):,} souls. Variants: {build['variant_count']}.",
        f"All-state validation core owners: {build['wins']}/{build['owners']} wins ({100 * numeric(build, 'win_rate'):.1f}%).",
        f"95% interval: {100 * numeric(build, 'lower_95'):.1f}%–{100 * numeric(build, 'upper_95'):.1f}%.",
        f"Hero baseline: {100 * numeric(build, 'hero_win_rate'):.1f}% across {build['hero_matches']} matches.",
        f"Final-core order: {order['ordered_owners']}/{order['owners']} owners followed this order.",
        *even_state_lines(build),
        f"Generator: {metadata['effective']}. Status: {build['status']}.",
        *(
            [f"Fallback reason: {metadata['fallback_reason']}."]
            if metadata.get("fallback_reason")
            else []
        ),
        "",
    ]


def even_state_lines(build: dict[str, object]) -> list[str]:
    metadata = require_object_dict(build["generator"])
    evidence = (
        object_dict(build.get("state_evidence", metadata.get("state_evidence"))) or {}
    )
    row = object_dict((object_dict(evidence.get("1")) or {}).get("validation"))
    if row is None:
        return []
    if not row.get("owners"):
        return ["No matched even-state core owners."]
    return [
        f"Even-state core owners: {row['wins']}/{row['owners']} wins ({100 * numeric(row, 'win_rate'):.1f}%).",
        f"Even-state 95% interval: {100 * numeric(row, 'lower_95'):.1f}%–{100 * numeric(row, 'upper_95'):.1f}%.",
        f"Even-state hero baseline: {100 * numeric(row, 'hero_win_rate'):.1f}% across {row['hero_matches']} matches.",
    ]


def render_report(rows: list[dict[str, object]], summary: dict[str, object]) -> str:
    lines = [
        "# Complete guide integration comparison",
        "",
        "This comparison uses previously examined data. It is exploratory.",
        "Core ownership means all final items owned strictly before 20 minutes. Additional items are permitted.",
        "Owner samples can overlap. Do not add variant match counts.",
        "Order counts measure final-core item order. They do not measure agreement with every component purchase.",
        "The score is an observational search heuristic. These results do not prove a win-rate benefit.",
        "",
        f"Compared {summary['groups']} groups across {summary['heroes']} heroes.",
        "",
    ]
    for row in rows:
        lines.extend([f"## {row['hero']} — build {row['number']}", ""])
        lines.extend(build_lines("Current master", require_object_dict(row["current"])))
        lines.extend(
            build_lines("Beam ordering control", require_object_dict(row["beam-order"]))
        )
        lines.extend(
            build_lines("Beam core and order", require_object_dict(row["beam"]))
        )
    return "\n".join(lines)


def rendered_summary(directory: Path, artifact_id: object) -> dict[str, object]:
    index_path = directory / "builds.json"
    if not index_path.exists():
        return {"complete": False}
    if read_document(directory / "generation.json")["source_artifact"] != artifact_id:
        return {
            "complete": False,
            "reason": "Guides refer to a different evidence artifact",
        }
    index = read_document(index_path)
    guides = require_object_rows(
        read_document(Path(str(index["directory"])) / "guides.json")["guides"]
    )
    variants = [
        variant
        for guide in guides
        for variant in require_object_rows(
            require_object_dict(guide["guide_group"])["variants"]
        )
    ]
    displays = [
        object_dict(
            require_object_dict(
                require_object_rows(
                    require_object_dict(guide["guide_group"])["variants"]
                )[0]["evidence"]
            ).get("display")
        )
        or {}
        for guide in guides
    ]
    return {
        "complete": True,
        "groups": len(guides),
        "variants": len(variants),
        "ability_orders": sum(
            len(require_object_list(variant["ability_order"])) == 16
            for variant in variants
        ),
        "overflow_groups": sum(
            layout_overflow(require_object_rows(guide["steam_categories"]))
            for guide in guides
        ),
        "omitted_compact_variants": sum(
            integer(row.get("omitted_variants"), default=0) for row in displays
        ),
        "omitted_compact_tier_items": sum(
            integer(row.get("omitted_tier_items"), default=0) for row in displays
        ),
    }


def layout_overflow(categories: list[dict[str, object]]) -> bool:
    x = y = height = maximum_width = 0.0
    for category in categories:
        width, item_height = numeric(category, "width"), numeric(category, "height")
        gap = 12 if x else 0
        if x and x + gap + width > 900:
            y += height + 12
            x = height = gap = 0
        x += gap + width
        height = max(height, item_height)
        maximum_width = max(maximum_width, x)
    return maximum_width > 900 or y + height > 650


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    root = args.root
    documents = {
        mode: read_document(root / mode / "build-evidence.json") for mode in MODES
    }
    assets = require_object_rows(
        json.loads(
            (root / "source/results/master-0ecad50/raw/items-all.json").read_text(
                encoding="utf-8"
            )
        )
    )
    names = {integer(item["id"]): str(item["name"]) for item in assets}
    rows = compare_groups(documents, names)
    states_path = root / "current-state-statistics.json"
    if states_path.exists():
        states = read_document(states_path)
        for row in rows:
            require_object_dict(row["current"])["state_evidence"] = states[
                str(row["group"])
            ]
    summary = comparison_totals(rows)
    summary["rendered"] = {
        mode: rendered_summary(root / mode, documents[mode]["artifact_id"])
        for mode in MODES
    }
    atomic_write_json(
        root / "comparison.json",
        {"exploratory": True, "summary": summary, "groups": rows},
    )
    atomic_write_bytes(root / "comparison.md", render_report(rows, summary).encode())


if __name__ == "__main__":
    main()
