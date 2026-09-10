"""Measure declared validation sensitivities without opening test evidence."""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from .benchmark import BenchmarkContext, decision_records, guide_records, summarize
from .dataset import DEFAULT_OUTPUT, DEFAULT_SOURCE, load_catalog
from .model import ItemModel
from .records import ScoringConfig, SearchConfig


@dataclass(frozen=True)
class ExperimentCase:
    name: str
    search: SearchConfig
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    joint_support: int = 100


def experiment_cases() -> tuple[ExperimentCase, ...]:
    beam = SearchConfig("beam", 16)
    cases = [
        ExperimentCase(f"beam_width_{width}", replace(beam, width=width))
        for width in (4, 8, 16, 32, 64)
    ]
    cases.append(ExperimentCase("greedy", SearchConfig()))
    cases.extend(
        ExperimentCase(
            f"{method}_width_{width}", replace(beam, method=method, width=width)
        )
        for method in ("diverse", "eclat", "leiden")
        for width in (8, 16, 32)
    )
    cases.extend(
        ExperimentCase(f"prior_{prior}", beam, ScoringConfig(prior_strength=prior))
        for prior in (20, 300, 1000)
    )
    cases.extend(
        ExperimentCase(
            f"cost_exponent_{exponent}", beam, ScoringConfig(cost_exponent=exponent)
        )
        for exponent in (0, 1)
    )
    cases.append(ExperimentCase("stateless", beam, ScoringConfig(state_aware=False)))
    cases.extend(
        ExperimentCase(f"depth_{depth}", replace(beam, depth=depth))
        for depth in (4, 6, 12)
    )
    cases.extend(
        ExperimentCase(f"joint_support_{count}", beam, joint_support=count)
        for count in (50, 200)
    )
    cases.extend(
        ExperimentCase(
            f"diversity_{strength}", replace(beam, method="diverse", diversity=strength)
        )
        for strength in (0.05, 0.1)
    )
    cases.extend(
        ExperimentCase(
            f"combined_prior_{prior}_support_{support}_depth_{depth}_cost_{cost}",
            replace(beam, depth=depth),
            ScoringConfig(prior_strength=prior, cost_exponent=cost),
            support,
        )
        for prior in (300, 1000)
        for support in (100, 200)
        for depth in (6, 8)
        for cost in (0, 0.5)
    )
    return tuple(cases)


def run_sensitivity(arguments: argparse.Namespace) -> None:
    catalog = load_catalog(arguments.source)
    structures = json.loads(arguments.structures.read_text(encoding="utf-8"))
    statistics = json.loads(
        (arguments.data / "train/statistics.json").read_text(encoding="utf-8")
    )
    heldout = json.loads(
        (arguments.data / "validation/statistics.json").read_text(encoding="utf-8")
    )
    if structures["data_fingerprint"] != statistics["fingerprint"]:
        raise ValueError("Structure proposals do not match the training data")
    results = []
    arguments.output.mkdir(parents=True, exist_ok=True)
    for case in experiment_cases():
        destination = arguments.output / f"{case.name}.json"
        if arguments.cases and not any(
            case.name.startswith(prefix) for prefix in arguments.cases
        ):
            continue
        model = ItemModel(statistics, case.scoring)
        context = BenchmarkContext(
            catalog,
            model,
            arguments.data,
            "validation",
            model.heroes,
            structures["heroes"],
            case.joint_support,
        )
        started = time.perf_counter()
        guides = guide_records(context, case.search)
        guide_summary = summarize(guides, "guides")
        guide_summary["total_evaluation_seconds"] = time.perf_counter() - started
        started = time.perf_counter()
        decisions = decision_records(context, case.search, arguments.sample_size)
        decision_summary = summarize(decisions, "decisions")
        decision_summary["total_evaluation_seconds"] = time.perf_counter() - started
        summary = {
            "case": asdict(case),
            "guides": guide_summary,
            "decisions": decision_summary,
            "calibration": model.calibration(heldout),
        }
        document = {
            "partition": "validation",
            "data_fingerprint": model.fingerprint,
            **summary,
            "guide_records": guides,
            "decision_records": decisions,
        }
        destination.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        results.append(summary)
        sys.stdout.write(json.dumps(summary) + "\n")
        sys.stdout.flush()
    (arguments.output / "summary.json").write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare validation sensitivities")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--data", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--structures", type=Path, required=True)
    parser.add_argument("--sample-size", type=int, default=24)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cases", nargs="+")
    run_sensitivity(parser.parse_args())


if __name__ == "__main__":
    main()
