"""Evaluate already frozen core nominations on later chronological matches."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from itertools import combinations
from pathlib import Path

import numpy as np
from scipy.stats import norm

from experiments.core_discovery.candidates import METHODS, ownership, valid_core
from experiments.core_discovery.data import HeroData, load_hero, write_json
from experiments.core_discovery.discover import source_fingerprints
from experiments.core_discovery.quality import (
    context_cells,
    evaluate_core,
    rejection_reasons,
)
from experiments.core_discovery.report import render
from experiments.qdfm.extract import HEROES, fingerprint


def key(hero: int, items: list[int]) -> str:
    return f"{hero}/" + "-".join(str(item) for item in items)


def verify_trial(runs: Path) -> tuple[dict, Path, list[dict], dict]:
    manifest = json.loads((runs / "manifest.json").read_text())
    if manifest["source_sha256"] != source_fingerprints():
        raise ValueError("Discovery/selection source changed after freezing nominees")
    if manifest["nominations_sha256"] != fingerprint(runs / "nominations.json"):
        raise ValueError("Frozen nominations changed")
    directory = Path(manifest["directory"])
    if manifest["data_manifest_sha256"] != fingerprint(directory / "manifest.json"):
        raise ValueError("Discovery dataset identity changed")
    data_manifest = json.loads((directory / "manifest.json").read_text())
    for name, expected in data_manifest["files"].items():
        if fingerprint(directory / name) != expected:
            raise ValueError(f"Frozen dataset file changed: {name}")
    models = {}
    for hero in HEROES:
        if manifest["hero_report_sha256"][str(hero)] != fingerprint(
            runs / f"hero-{hero}.json"
        ):
            raise ValueError("Discovery model report changed")
        models[str(hero)] = json.loads((runs / f"hero-{hero}.json").read_text())
    return (
        manifest,
        directory,
        json.loads((runs / "nominations.json").read_text()),
        models,
    )


def current_order(data: HeroData, items: list[int], order: list[int]) -> dict | None:
    if not order:
        return None
    index = {item: column for column, item in enumerate(data.items)}
    rows = data.mask("validation")
    owners = ownership(data.matrix[rows], tuple(index[item] for item in items))
    times = data.times[rows][:, [index[item] for item in order]]
    follows = (times[:, 0] >= 0) & (np.diff(times, axis=1) > 0).all(axis=1)
    count = int((owners & follows).sum())
    return {
        "items": order,
        "owners_in_order": count,
        "fraction_of_core_owners": count / max(1, int(owners.sum())),
        "definition": "Strict order of currently held items' latest acquisitions",
    }


def coverage(
    data: dict[int, HeroData], nominees: list[dict], results: dict, method: str
) -> dict:
    covered, wins, population, shared_pairs, pairs = 0, 0, 0, 0, 0
    owner_jaccards = []
    heroes = []
    for hero, hero_data in data.items():
        rows = hero_data.mask("validation")
        matrix = hero_data.matrix[rows]
        index = {item: column for column, item in enumerate(hero_data.items)}
        accepted = [
            row
            for row in nominees
            if row["hero_id"] == hero
            and row["method"] == method
            and results[key(hero, row["items"])]["passes_observational_gate"]
        ]
        masks = [
            ownership(matrix, tuple(index[item] for item in row["items"]))
            for row in accepted
        ]
        selected = (
            np.logical_or.reduce(masks) if masks else np.zeros(len(matrix), dtype=bool)
        )
        covered += int(selected.sum())
        wins += int(hero_data.won[rows][selected].sum())
        population += len(matrix)
        if accepted:
            heroes.append(hero)
        for first, second in combinations(range(len(accepted)), 2):
            pairs += 1
            shared_pairs += (
                len(set(accepted[first]["items"]) & set(accepted[second]["items"])) >= 2
            )
            owner_jaccards.append(
                float(
                    (masks[first] & masks[second]).sum()
                    / max(1, (masks[first] | masks[second]).sum())
                )
            )
    return {
        "covered_hero_matches": covered,
        "total_hero_matches": population,
        "coverage": covered / population,
        "covered_observed_win_rate": wins / covered if covered else None,
        "heroes_with_replicated_core": heroes,
        "pairs_sharing_at_least_two_items": int(shared_pairs),
        "within_hero_core_pairs": pairs,
        "mean_owner_jaccard": float(np.mean(owner_jaccards))
        if owner_jaccards
        else None,
    }


def method_summary(
    method: str,
    models: dict,
    nominations: list[dict],
    results: dict,
    data: dict[int, HeroData],
) -> dict:
    runs = [result[method] for result in models.values()]
    chosen = [row for row in nominations if row["method"] == method]
    return {
        "fits_completed": sum(len(result["seeds"]) for result in runs),
        "discovery_candidates_across_heroes": sum(
            result["union_candidates"] for result in runs
        ),
        "candidates_in_all_seeds": sum(
            result["all_seed_candidates"] for result in runs
        ),
        "selection_eligible_before_cap": sum(
            result["eligible_before_cap"] for result in runs
        ),
        "nominated": len(chosen),
        "replicated": sum(
            results[key(row["hero_id"], row["items"])]["passes_observational_gate"]
            for row in chosen
        ),
        "runtime_s": sum(
            seed["runtime_s"] for result in runs for seed in result["seeds"]
        ),
        "selection_rejections": dict(
            Counter(
                reason
                for result in runs
                for candidate in result["candidates"]
                for reason in candidate["selection_rejections"]
            )
        ),
        **coverage(data, nominations, results, method),
    }


def run(runs: Path) -> None:
    manifest, directory, nominations, models = verify_trial(runs)
    catalog = json.loads((directory / "catalog.json").read_text())
    data = {hero: load_hero(directory, hero) for hero in HEROES}
    unique = {key(row["hero_id"], row["items"]): row for row in nominations}
    hypotheses = len(unique)
    critical = float(norm.isf(0.025 / max(1, hypotheses)))
    results = {}
    for identity, row in unique.items():
        if not valid_core(tuple(row["items"]), catalog):
            raise ValueError("Frozen nominee violates core contract")
        hero_data = data[row["hero_id"]]
        validation = evaluate_core(hero_data, tuple(row["items"]), "validation")
        reasons = rejection_reasons(validation, hypotheses)
        adjusted = validation["adjusted"]
        validation["adjusted_lower_family"] = (
            adjusted["difference"] - critical * adjusted["standard_error"]
            if adjusted["difference"] is not None
            else None
        )
        contributing = [
            nominee
            for nominee in nominations
            if key(nominee["hero_id"], nominee["items"]) == identity
        ]
        results[identity] = {
            "hero_id": row["hero_id"],
            "hero": row["hero"],
            "items": row["items"],
            "names": row["names"],
            "cost": row["cost"],
            "methods": [nominee["method"] for nominee in contributing],
            "selection": row["selection"],
            "validation": validation,
            "passes_observational_gate": not reasons,
            "validation_rejections": reasons,
            "production_build_created": False,
            "order_evidence": [
                evidence
                for nominee in contributing
                if (
                    evidence := current_order(
                        hero_data, nominee["items"], nominee["order"]
                    )
                )
                is not None
            ],
            "context_cells": context_cells(hero_data, tuple(row["items"])),
        }
    data_manifest = json.loads((directory / "manifest.json").read_text())
    report = {
        "goal": "Implement and evaluate five previously unused discovery algorithms",
        "methods": {
            method: method_summary(method, models, nominations, results, data)
            for method in METHODS
        },
        "hero_groups": HEROES,
        "data": data_manifest,
        "union_nominated_hypotheses": hypotheses,
        "union_replicated_cores": sum(
            result["passes_observational_gate"] for result in results.values()
        ),
        "correction": {
            "families": 2,
            "alpha_per_family": 0.025,
            "hypotheses_per_family": hypotheses,
            "one_sided_threshold": 0.025 / max(1, hypotheses),
        },
        "cores": results,
        "source_sha256": {
            name: fingerprint(Path(__file__).parent / name)
            for name in ("evaluate.py", "report.py")
        },
        "discovery_manifest_sha256": fingerprint(runs / "manifest.json"),
        "frozen_nominations_sha256": manifest["nominations_sha256"],
        "validation_evaluated": True,
        "test_evaluated": False,
        "promotion": False,
        "limits": [
            "Observed core ownership associations do not identify the effect of purchasing these items.",
            "Current wealth and lead may already reflect earlier purchases; opponent/skill/player confounding remains.",
            "Fixed 20-minute survivor cohort; three tier-2+ items and a 12,800-soul ceiling bound this experiment.",
            "The cohort spans balance changes; no per-match historical mechanics certification.",
            "Validation was examined in previous research; this is exploratory despite fresh outcome-blind discovery.",
            "Core candidates may overlap heavily; three different triples do not necessarily imply three distinct identities.",
            "Enemy/wealth cells are descriptive tuning clues with no multiple-testing-based counter recommendations.",
            "Full item order, affordability, slots, tactical review, and adaptive future paths remain separate work.",
        ],
    }
    write_json(runs / "evaluation.json", report)
    render(report, runs)
    print(
        json.dumps(
            {
                "methods": report["methods"],
                "unique_nominations": hypotheses,
                "unique_replicated": report["union_replicated_cores"],
            },
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", required=True, type=Path)
    args = parser.parse_args()
    run(args.runs)
