"""Independent planted-core check for all five discovery algorithms."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from threadpoolctl import threadpool_limits

from tools.comparisons.core_discovery.candidates import METHODS
from tools.comparisons.core_discovery.data import HeroData, write_json
from tools.comparisons.core_discovery.discover import fit_method, source_fingerprints
from tools.comparisons.core_discovery.quality import evaluate_core, rejection_reasons
from tools.comparisons.qdfm.extract import fingerprint


def planted_data(seed: int = 91, per_fold: int = 9000) -> tuple[HeroData, dict]:
    rng = np.random.default_rng(seed)
    count, dimensions = 3 * per_fold, 15
    group = rng.integers(0, 3, size=count)
    matrix = rng.random((count, dimensions)) < 0.03
    matrix[:, 9:11] = rng.random((count, 2)) < 0.9
    times = rng.integers(100, 1150, size=(count, dimensions))
    for label in range(3):
        rows = group == label
        columns = np.arange(label * 3, label * 3 + 3)
        matrix[np.ix_(rows, columns)] = rng.random((int(rows.sum()), 3)) < 0.9
        times[np.ix_(rows, columns)] = [300, 550, 800]
    times[~matrix] = -1
    wealth = rng.normal(15000, 2500, count).clip(5000, 25000)
    items = tuple(range(100, 115))
    catalog = {
        str(item): {"name": f"Item {item}", "cost": 1600, "ancestors": []}
        for item in items
    }
    data = HeroData(
        0,
        items,
        matrix,
        times,
        np.arange(count),
        np.repeat(["discovery", "selection", "validation"], per_fold),
        rng.random(count) < np.asarray([0.70, 0.62, 0.35])[group],
        wealth,
        rng.normal(0, 0.04, count),
        np.full(count, 90),
        wealth / 15000,
        np.argsort(rng.random((count, 30)), axis=1)[:, :6] + 20,
    )
    return data, catalog


def run(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=False)
    data, catalog = planted_data()
    with threadpool_limits(limits=1):
        results = {method: fit_method(data, method, catalog) for method in METHODS}
    nominated = {
        tuple(candidate["items"])
        for result in results.values()
        for candidate in result["nominees"]
    }
    validated = {core: evaluate_core(data, core, "validation") for core in nominated}
    accepted = {
        core
        for core, result in validated.items()
        if not rejection_reasons(result, len(nominated))
    }
    truth = [(100, 101, 102), (103, 104, 105), (106, 107, 108)]
    summaries = {}
    for method, result in results.items():
        proposed = {tuple(candidate["items"]) for candidate in result["candidates"]}
        nominees = {tuple(candidate["items"]) for candidate in result["nominees"]}
        summaries[method] = {
            "planted_cores_recovered": [
                list(core) for core in truth if core in proposed
            ],
            "positive_planted_cores_replicated": [
                list(core) for core in truth[:2] if core in nominees & accepted
            ],
            "negative_planted_core_nominated": truth[2] in nominees,
            "nominated": len(nominees),
            "replicated": len(nominees & accepted),
        }
    write_json(
        output / "report.json",
        {
            "source_sha256": source_fingerprints(),
            "synthetic_script_sha256": fingerprint(Path(__file__)),
            "seed": 91,
            "per_fold": 9000,
            "latent_group_win_probabilities": [0.70, 0.62, 0.35],
            "planted_cores": truth,
            "summaries": summaries,
            "methods": results,
            "validation": [
                {
                    "items": core,
                    "result": result,
                    "rejections": rejection_reasons(result, len(nominated)),
                }
                for core, result in validated.items()
            ],
            "losing_core_direct_gate": rejection_reasons(
                evaluate_core(data, truth[2], "validation"), max(1, len(nominated))
            ),
            "interpretation": "Synthetic association/core-recovery check; not a match simulator or purchase-effect validation",
        },
    )
    print(summaries, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    run(args.output)
