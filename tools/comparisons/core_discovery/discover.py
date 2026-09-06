"""Discover core identities and freeze nominations before validation outcomes."""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path

import igraph
import leidenalg
import numpy as np
import scipy
import sklearn
from threadpoolctl import threadpool_limits

from tools.comparisons.core_discovery.candidates import METHODS, SEEDS, discover
from tools.comparisons.core_discovery.data import HeroData, load_hero, write_json
from tools.comparisons.core_discovery.quality import evaluate_core, rejection_reasons
from tools.comparisons.qdfm.extract import HEROES, fingerprint


def source_fingerprints() -> dict[str, str]:
    directory = Path(__file__).parent
    names = (
        "PROTOCOL.md",
        "candidates.py",
        "patterns.py",
        "latent.py",
        "quality.py",
        "data.py",
        "discover.py",
        "uv.lock",
    )
    return {
        **{name: fingerprint(directory / name) for name in names},
        **{
            str(path): fingerprint(path)
            for path in sorted(
                Path("src/deadlock_build_sync/offline").glob("discovery_*.py")
            )
        },
    }


def fit_method(data: HeroData, method: str, catalog: dict) -> dict:
    rows = data.mask("discovery")
    seeds = []
    for seed in SEEDS:
        started = time.monotonic()
        candidates, details = discover(
            method, data.matrix[rows], data.times[rows], data.items, catalog, seed
        )
        seeds.append({
            "seed": seed,
            "runtime_s": time.monotonic() - started,
            "candidates": candidates,
            "diagnostic": details,
        })
        print(
            f"hero={data.hero} method={method} seed={seed} candidates={len(candidates)} elapsed={seeds[-1]['runtime_s']:.1f}s",
            flush=True,
        )
    counts = Counter(
        tuple(candidate["items"]) for run in seeds for candidate in run["candidates"]
    )
    representatives = {
        tuple(candidate["items"]): candidate
        for run in reversed(seeds)
        for candidate in run["candidates"]
    }
    candidates = []
    for items, count in sorted(counts.items()):
        selection = evaluate_core(data, items, "selection")
        reasons = rejection_reasons(selection)
        if count < 2:
            reasons.append("appears in fewer than two seeds")
        candidates.append({
            **representatives[items],
            "seed_count": count,
            "selection": selection,
            "selection_rejections": reasons,
        })
    eligible = sorted(
        (
            candidate
            for candidate in candidates
            if not candidate["selection_rejections"]
        ),
        key=lambda row: (-row["selection"]["adjusted"]["lower_95"], row["items"]),
    )
    nominees = eligible[:3]
    overlap = set.intersection(
        *(
            {tuple(candidate["items"]) for candidate in run["candidates"]}
            for run in seeds
        )
    )
    return {
        "seeds": seeds,
        "union_candidates": len(counts),
        "all_seed_candidates": len(overlap),
        "candidates": candidates,
        "eligible_before_cap": len(eligible),
        "nominees": nominees,
    }


def run(directory: Path, output: Path) -> None:
    manifest = json.loads((directory / "manifest.json").read_text())
    for name, expected in manifest["files"].items():
        if fingerprint(directory / name) != expected:
            raise ValueError(f"Frozen discovery data changed: {name}")
    output.mkdir(parents=True, exist_ok=False)
    catalog = json.loads((directory / "catalog.json").read_text())
    models = {}
    with threadpool_limits(limits=1):
        for hero in HEROES:
            data = load_hero(directory, hero)
            models[str(hero)] = {
                method: fit_method(data, method, catalog) for method in METHODS
            }
            write_json(output / f"hero-{hero}.json", models[str(hero)])
    nominations = [
        {
            "hero_id": int(hero),
            "hero": HEROES[int(hero)][0],
            "method": method,
            **candidate,
        }
        for hero, methods in models.items()
        for method, result in methods.items()
        for candidate in result["nominees"]
    ]
    write_json(output / "nominations.json", nominations)
    write_json(
        output / "manifest.json",
        {
            "directory": str(directory.resolve()),
            "data_manifest_sha256": fingerprint(directory / "manifest.json"),
            "source_sha256": source_fingerprints(),
            "nominations_sha256": fingerprint(output / "nominations.json"),
            "hero_report_sha256": {
                str(hero): fingerprint(output / f"hero-{hero}.json") for hero in HEROES
            },
            "methods": list(METHODS),
            "seeds": list(SEEDS),
            "existing_build_labels_used": False,
            "validation_evaluated": False,
            "test_evaluated": False,
            "promotion": False,
            "versions": {
                "numpy": np.__version__,
                "scipy": scipy.__version__,
                "sklearn": sklearn.__version__,
                "igraph": igraph.__version__,
                "leidenalg": leidenalg.__version__,
            },
        },
    )
    print(f"Frozen {len(nominations)} method/core nominations", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    run(args.directory, args.output)
