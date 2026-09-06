"""Generate full local guides from frozen discoveries or recalculate a chosen path."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
from deadlock_build_sync.mechanics import ItemGraph

from experiments.build_guides.assemble import assemble
from experiments.build_guides.evidence import collect
from experiments.build_guides.paths import plan
from experiments.build_guides.render import markdown, render
from experiments.build_guides.schema import load_guide
from experiments.core_discovery.data import write_json
from experiments.identity_paths.config import ARMS
from experiments.identity_paths.storage import read_json, verify_run
from experiments.qdfm.extract import fingerprint


def verify_evaluation(runs: Path, nominations: list[dict]) -> dict:
    report = read_json(runs / "evaluation.json")
    if report["fit_manifest_sha256"] != fingerprint(runs / "manifest.json"):
        raise ValueError("Evaluation does not belong to the frozen identity run")
    for name, expected in report["source_sha256"].items():
        if fingerprint(Path("experiments/identity_paths") / name) != expected:
            raise ValueError("Frozen evaluation sources changed")
    original = {(row["arm"], row["identity_id"]): row for row in nominations}
    if len(report["previews"]) != len(original):
        raise ValueError("Evaluation is missing frozen nominees")
    for row in report["previews"]:
        nominee = original.get((row["arm"], row["identity_id"]))
        if nominee is None or any(row[key] != value for key, value in nominee.items()):
            raise ValueError("Evaluation changed a frozen core or purchase order")
    return report


def generate(
    runs: Path, output: Path, arm: str = ARMS[2], heroes: list[int] | None = None
) -> dict:
    if output.exists():
        raise FileExistsError(
            "Preserve existing previews; choose a new output directory"
        )
    manifest, nominations = verify_run(runs)
    report = verify_evaluation(runs, nominations)
    if arm not in ARMS:
        raise ValueError("Unknown discovery configuration")
    if heroes and set(heroes) - {int(hero) for hero in report["heroes"]}:
        raise ValueError("Requested hero is outside the frozen experiment")
    directory = Path(manifest["directory"])
    source = Path(read_json(directory / "manifest.json")["source"])
    asset_path = source / "raw/items.json"
    assets = read_json(asset_path)
    graph = ItemGraph.from_assets(assets)
    by_id = {item["id"]: item for item in assets}
    rows = [
        row
        for row in report["previews"]
        if row["arm"] == arm and (not heroes or row["hero_id"] in heroes)
    ]
    con = duckdb.connect(str(source / "raw/analysis.duckdb"), read_only=True)
    con.execute("SET threads=2")
    con.execute("SET memory_limit='2GB'")
    guides = []
    try:
        for row in rows:
            evidence = collect(con, directory, row)
            guide = assemble(row, graph, by_id, evidence)
            guide["catalog_source"] = {
                "path": str(asset_path),
                "sha256": fingerprint(asset_path),
            }
            guides.append(guide)
            print(
                f"{row['hero']} / {row['identity_id']}: {len(guide['choices'])} pool items, {sum(card['branch'] is not None for card in guide['choices'])} legal choices",
                flush=True,
            )
    finally:
        con.close()
    return emit(
        runs, output, arm, guides, manifest, defaults_for(report, guides, heroes)
    )


def defaults_for(report: dict, guides: list[dict], heroes: list[int] | None) -> dict:
    names = {int(hero): value[0] for hero, value in report["heroes"].items()}
    defaults = dict.fromkeys(names[hero] for hero in (heroes or list(names)))
    for guide in guides:
        if guide["core_path_supported"] and defaults[guide["hero"]] is None:
            defaults[guide["hero"]] = guide["identity_id"]
    return defaults


def emit(
    runs: Path,
    output: Path,
    arm: str,
    guides: list[dict],
    manifest: dict,
    defaults: dict,
) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    for guide in guides:
        write_json(output / f"{guide['identity_id']}.json", guide)
    render(guides, output)
    summary = {
        "schema_version": 2,
        "identity_run": str(runs.resolve()),
        "fit_manifest_sha256": fingerprint(runs / "manifest.json"),
        "evaluation_sha256": fingerprint(runs / "evaluation.json"),
        "source_sha256": manifest["source_sha256"],
        "producer_sha256": {
            str(path): fingerprint(path)
            for path in sorted(Path(__file__).parent.iterdir())
            if path.suffix in {".py", ".html", ".md"}
        },
        "arm": arm,
        "default_identities": defaults,
        "guides": len(guides),
        "pool_items": sum(len(g["choices"]) for g in guides),
        "legal_choices": sum(
            card["branch"] is not None for g in guides for card in g["choices"]
        ),
        "unplaced_choices": sum(len(g["unplaced_choices"]) for g in guides),
        "blocked_choices": sum(len(g["blocked_choices"]) for g in guides),
        "test_fold_read": False,
        "existing_build_pools_used": False,
        "production_promotion": False,
        "files": {path.name: fingerprint(path) for path in sorted(output.iterdir())},
    }
    write_json(output / "manifest.json", summary)
    return summary


def replan(guide_path: Path, state_path: Path) -> dict:
    guide, graph = load_guide(guide_path)
    state = read_json(state_path)
    if not isinstance(state, dict):
        raise TypeError("State must be an object")
    unknown = set(state) - {
        "owned_items",
        "selected_items",
        "liquid_souls",
        "unlocked_flex_slots",
        "placement_overrides",
    }
    if unknown:
        raise ValueError(f"Unsupported state fields: {sorted(unknown)}")
    result = plan(
        graph,
        guide,
        state.get("selected_items", []),
        owned=state.get("owned_items", []),
        liquid_souls=state.get("liquid_souls"),
        flex=state.get("unlocked_flex_slots", 0),
        placement_overrides=state.get("placement_overrides"),
    )
    return {
        "hero": guide["hero"],
        "identity_id": guide["identity_id"],
        "core_path_supported": guide["core_path_supported"],
        "full_policy_validated": False,
        **result,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    preview = commands.add_parser("preview")
    preview.add_argument("--runs", type=Path, required=True)
    preview.add_argument("--output", type=Path, required=True)
    preview.add_argument("--arm", choices=ARMS, default=ARMS[2])
    preview.add_argument("--heroes", type=int, nargs="+")
    update = commands.add_parser("plan")
    update.add_argument("--guide", type=Path, required=True)
    update.add_argument("--state", type=Path, required=True)
    show = commands.add_parser("show")
    show.add_argument("--guide", type=Path, required=True)
    show.add_argument("--format", choices=["markdown"], default="markdown")
    show.add_argument("--details", action="store_true")
    args = parser.parse_args()
    if args.command == "preview":
        result = generate(args.runs, args.output, args.arm, args.heroes)
        print(
            json.dumps(
                {
                    key: result[key]
                    for key in (
                        "guides",
                        "pool_items",
                        "legal_choices",
                        "default_identities",
                    )
                },
                indent=2,
            )
        )
    elif args.command == "plan":
        print(json.dumps(replan(args.guide, args.state), indent=2, allow_nan=False))
    else:
        guide, _ = load_guide(args.guide)
        print(markdown(guide, details=args.details))


if __name__ == "__main__":
    main()
