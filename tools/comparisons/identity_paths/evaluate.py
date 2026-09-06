"""Evaluate immutable nominations; core, tactics and sequence gates stay separate."""

from __future__ import annotations

import time
from itertools import combinations
from pathlib import Path

import numpy as np
from scipy.stats import norm

from tools.comparisons.core_discovery.candidates import ownership
from tools.comparisons.core_discovery.data import HeroData, load_hero, write_json
from tools.comparisons.core_discovery.quality import evaluate_core, rejection_reasons
from tools.comparisons.identity_paths.config import ARMS, SCHEMA_VERSION
from tools.comparisons.identity_paths.mining import valid_items
from tools.comparisons.identity_paths.orders import core_times, order_evidence
from tools.comparisons.identity_paths.report import render
from tools.comparisons.identity_paths.storage import read_json, verify_run
from tools.comparisons.qdfm.extract import HEROES, fingerprint


def coverage(rows: list[dict], data: dict[int, HeroData], cores: dict) -> dict:
    covered, wins, population, overlaps = 0, 0, 0, []
    for hero, values in data.items():
        mask = values.mask("validation")
        population += int(mask.sum())
        index = {item: column for column, item in enumerate(values.items)}
        owned = [
            ownership(values.matrix[mask], tuple(index[item] for item in row["items"]))
            for row in rows
            if row["hero_id"] == hero and cores[row["identity_id"]]["passes_core_gate"]
        ]
        if not owned:
            continue
        union = np.logical_or.reduce(owned)
        covered += int(union.sum())
        wins += int(values.won[mask][union].sum())
        overlaps.extend(
            float((first & second).sum() / max(1, int((first | second).sum())))
            for first, second in combinations(owned, 2)
        )
    return {
        "covered_hero_matches": covered,
        "population": population,
        "coverage": covered / max(1, population),
        "covered_observed_win_rate": wins / covered if covered else None,
        "within_hero_pairs": len(overlaps),
        "mean_owner_jaccard": float(np.mean(overlaps)) if overlaps else None,
        "pairs_jaccard_at_least_070": sum(value >= 0.70 for value in overlaps),
    }


def validate_core(row: dict, data: HeroData, hypotheses: int, catalog: dict) -> dict:
    if len(row["items"]) < 4 or not valid_items(tuple(row["items"]), catalog):
        raise ValueError("Nomination violates the frozen core contract")
    result = evaluate_core(data, tuple(row["items"]), "validation")
    reasons = rejection_reasons(result, hypotheses)
    adjusted = result["adjusted"]
    critical = float(norm.isf(0.025 / max(1, hypotheses)))
    result["adjusted_lower_family"] = (
        adjusted["difference"] - critical * adjusted["standard_error"]
        if adjusted["difference"] is not None
        else None
    )
    return {
        "identity_id": row["identity_id"],
        "hero_id": data.hero,
        "items": row["items"],
        "names": row["names"],
        "validation": result,
        "passes_core_gate": not reasons,
        "rejections": reasons,
    }


def validate_path(row: dict, data: HeroData, core: dict) -> dict:
    path = row["path"]
    evidence = (
        order_evidence(
            core_times(data, row["items"], "validation"), row["items"], path["order"]
        )
        if path["order"]
        else None
    )
    passes = bool(
        evidence and evidence["passes"] and path["admitted_before_validation"]
    )
    identity = core["passes_core_gate"] and row["tactics"]["supported_focus"]
    reasons = list(core["rejections"])
    if not row["tactics"]["supported_focus"]:
        reasons.append(row["tactics"]["reason"])
    if not passes:
        reasons.append(
            "Frozen order does not meet discovery/selection/validation support"
        )
    if not path["legal"]:
        reasons.append("No legal component-expanded path")
    return {
        **row,
        "core_validation": core["validation"],
        "passes_core_gate": core["passes_core_gate"],
        "passes_identity_gate": identity,
        "order_validation": evidence,
        "passes_sequence_gate": passes,
        "complete_preview": identity and passes and path["legal"],
        "preview_rejections": reasons,
    }


def summarize(
    arm: str, rows: list[dict], data: dict, cores: dict, models: dict
) -> dict:
    selected = [row for row in rows if row["arm"] == arm]
    return {
        "nominated": len(selected),
        "validated_cores": sum(row["passes_core_gate"] for row in selected),
        "explained_identities": sum(row["passes_identity_gate"] for row in selected),
        "supported_orders": sum(row["passes_sequence_gate"] for row in selected),
        "legal_paths": sum(row["path"]["legal"] for row in selected),
        "complete_previews": sum(row["complete_preview"] for row in selected),
        "order_runtime_s": sum(row["path"]["runtime_s"] for row in selected),
        "discovery_runtime_s": sum(model["mine_seconds"] for model in models.values()),
        "group_runtime_s": 0
        if arm == ARMS[0]
        else sum(model["group_seconds"] for model in models.values()),
        **coverage(selected, data, cores),
    }


def run(runs: Path) -> None:
    if (runs / "evaluation.json").exists():
        raise FileExistsError("Evaluation already exists; preserve prior artifacts")
    started = time.monotonic()
    manifest, nominations = verify_run(runs)
    directory = Path(manifest["directory"])
    data = {hero: load_hero(directory, hero) for hero in HEROES}
    catalog = read_json(directory / "catalog.json")
    models = {str(hero): read_json(runs / f"hero-{hero}.json") for hero in HEROES}
    unique = {row["identity_id"]: row for row in nominations}
    cores = {
        identity: validate_core(row, data[row["hero_id"]], max(1, len(unique)), catalog)
        for identity, row in unique.items()
    }
    rows = [
        validate_path(row, data[row["hero_id"]], cores[row["identity_id"]])
        for row in nominations
    ]
    report = {
        "schema_version": SCHEMA_VERSION,
        "heroes": HEROES,
        "data_manifest": read_json(directory / "manifest.json"),
        "unique_hypotheses": len(unique),
        "unique_validated_cores": sum(
            row["passes_core_gate"] for row in cores.values()
        ),
        "correction": {
            "families": 2,
            "alpha_each": 0.025,
            "hypotheses_each": len(unique),
        },
        "arms": {arm: summarize(arm, rows, data, cores, models) for arm in ARMS},
        "discovery": {
            hero: {key: model[key] for key in ("sizes", "selected")}
            | {"groups": len(model["grouping"]["groups"])}
            for hero, model in models.items()
        },
        "cores": cores,
        "previews": rows,
        "evaluation_runtime_s": time.monotonic() - started,
        "fit_manifest_sha256": fingerprint(runs / "manifest.json"),
        "source_sha256": {
            name: fingerprint(Path(__file__).parent / name)
            for name in ("evaluate.py", "report.py")
        },
        "validation_evaluated": True,
        "test_evaluated": False,
        "production_promotion": False,
    }
    write_json(runs / "evaluation.json", report)
    render(report, runs)
    print(
        f"Evaluated {len(unique)} unique cores; {report['unique_validated_cores']} passed",
        flush=True,
    )
