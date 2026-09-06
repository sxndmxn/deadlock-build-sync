"""Screen co-admitted item pairs, then check later-fold negative interactions."""

from __future__ import annotations

import argparse
import json
from itertools import combinations
from pathlib import Path

import duckdb
import numpy as np

from tools.comparisons.qdfm.build_pool import load_pools
from tools.comparisons.qdfm.combo_stats import bh_adjust, stratified_contrast
from tools.comparisons.qdfm.extract import HEROES, fingerprint
from tools.comparisons.qdfm.state import Catalog


def read_arrays(directory: Path) -> dict:
    con = duckdb.connect()
    columns = con.execute(
        """
        SELECT hero_id, landmark, fold, wealth, team_lead_share, average_badge,
               won::INTEGER AS won, match_id, owned_items
        FROM read_parquet(?)
    """,
        [str(directory / "landmarks.parquet")],
    ).fetchnumpy()
    con.close()
    return columns


def evaluate_pair(first: int, second: int, data: dict, indices: np.ndarray) -> dict:
    owned = data["owned_items"][indices]
    # Current observations are adjustment variables, never final wealth or duration.
    encoded = np.column_stack((
        data["wealth"][indices] // 5000,
        np.digitize(data["team_lead_share"][indices], [-0.10, -0.03, 0.03, 0.10]),
        data["average_badge"][indices] // 20,
    ))
    _, strata = np.unique(encoded, axis=0, return_inverse=True)
    return stratified_contrast(
        np.array([first in items for items in owned]),
        np.array([second in items for items in owned]),
        data["won"][indices],
        strata,
    )


def candidate_pairs(paths: list, catalog: Catalog) -> list[tuple[int, int]]:
    return sorted({
        pair
        for pool in paths
        for pair in combinations(
            sorted(item for item in pool.item_ids if catalog.costs[item] >= 1600), 2
        )
        if pair[0] not in catalog.ancestors[pair[1]]
        and pair[1] not in catalog.ancestors[pair[0]]
    })


def screen(data: dict, pools: list, catalog: Catalog) -> list[dict]:
    results = []
    for hero_id in HEROES:
        paths = [pool for pool in pools if pool.hero_id == hero_id]
        pairs = candidate_pairs(paths, catalog)
        indices = np.flatnonzero(
            (data["hero_id"] == hero_id)
            & (data["landmark"] == 1200)
            & (data["fold"] == "train")
        )
        # Precompute membership and adjustment strata once for each hero.
        item_ids = sorted({item for pair in pairs for item in pair})
        owned = data["owned_items"][indices]
        membership = {
            item: np.array([item in items for items in owned]) for item in item_ids
        }
        _, strata = np.unique(
            np.column_stack((
                data["wealth"][indices] // 5000,
                np.digitize(
                    data["team_lead_share"][indices], [-0.10, -0.03, 0.03, 0.10]
                ),
                data["average_badge"][indices] // 20,
            )),
            axis=0,
            return_inverse=True,
        )
        for first, second in pairs:
            result = stratified_contrast(
                membership[first], membership[second], data["won"][indices], strata
            )
            results.append({
                "hero_id": hero_id,
                "hero": HEROES[hero_id][0],
                "first_id": first,
                "first": catalog.names[first],
                "second_id": second,
                "second": catalog.names[second],
                "co_admitted_path_ids": [
                    p.path_id for p in paths if {first, second} <= p.item_ids
                ],
                "train": result,
                "validation": None,
            })
        print(
            f"Screened {HEROES[hero_id][0]}: {len(pairs)} candidate pairs", flush=True
        )
    return results


def replicate(results: list[dict], data: dict) -> list[dict]:
    estimable = [row for row in results if row["train"]["adjusted"] is not None]
    pvalues = [
        row["train"]["adjusted"]["interaction"]["two_sided_p"] for row in estimable
    ]
    discoveries = []
    for row, qvalue in zip(estimable, bh_adjust(pvalues), strict=True):
        row["train_interaction_q"] = qvalue
        if qvalue < 0.05 and row["train"]["adjusted"]["interaction"]["difference"] < 0:
            discoveries.append(row)
    for row in discoveries:
        indices = np.flatnonzero(
            (data["hero_id"] == row["hero_id"])
            & (data["landmark"] == 1200)
            & (data["fold"] == "validation")
        )
        row["validation"] = evaluate_pair(
            row["first_id"], row["second_id"], data, indices
        )
        adjusted = row["validation"]["adjusted"]
        row["replicated_negative_interaction"] = bool(
            adjusted
            and adjusted["interaction"]["difference"] < 0
            and adjusted["interaction"]["two_sided_p"] < 0.05 / len(discoveries)
        )
    return discoveries


def requested_pair(data: dict) -> list[dict]:
    rows = []
    for hero_id in (6, 12):
        for time in (900, 1200, 1500):
            for fold in ("train", "validation"):
                indices = np.flatnonzero(
                    (data["hero_id"] == hero_id)
                    & (data["landmark"] == time)
                    & (data["fold"] == fold)
                )
                rows.append({
                    "hero": HEROES[hero_id][0],
                    "landmark_s": time,
                    "fold": fold,
                    "first": "Weighted Shots",
                    "second": "Point Blank",
                    "result": evaluate_pair(3791587546, 2095565695, data, indices),
                })
    return rows


def render(report: dict, output: Path) -> None:
    lines = [
        "# Item-combination association screen",
        "",
        "Current ownership at fixed game times; sold items and consumed components are removed. Only training and validation folds are read.",
        "This screen uses all available eligible appearances for the nine heroes, not the complete-trajectory QDFM pilot subset.",
        "Adjustment uses current wealth, team wealth lead, and rank. Current wealth may itself reflect earlier item choices: these are associations, not causal purchase effects.",
        "The four groups are neither item, first only, second only, and both. Negative interaction means the joint association is below the additive expectation; it does not automatically mean the pair loses more than either item alone.",
        "The primary screen is at 20 minutes. Other times below describe the requested pair only. Matches repeated across times are not independent evidence.",
        "",
        f"Scanned {report['candidate_pairs']} hero/pair candidates; {report['estimable_pairs']} had enough common-stratum support.",
        f"Training discoveries after multiple-comparison correction: {len(report['discoveries'])}. Later-fold replications: {report['replications']}.",
        "",
        "## Weighted Shots + Point Blank",
        "",
        "| Hero | Time | Fold | Both: n / raw wins | Both in overlap | Adjusted both - Weighted only | Adjusted interaction (approx. 95% interval) |",
        "| --- | ---: | --- | ---: | ---: | ---: | --- |",
    ]
    for row in report["requested_pair"]:
        result = row["result"]
        both, adjusted = result["groups"]["both"], result["adjusted"]
        raw = (
            f"{both['n']:,} / {both['win_rate']:.1%}"
            if both["n"]
            else "0 / unavailable"
        )
        difference = (
            f"{adjusted['both_minus_first_only']['difference'] * 100:+.1f} pp"
            if adjusted
            else "insufficient overlap"
        )
        interaction = adjusted["interaction"] if adjusted else None
        value = (
            f"{interaction['difference'] * 100:+.1f} pp [{interaction['approximate_95_interval'][0] * 100:+.1f}, {interaction['approximate_95_interval'][1] * 100:+.1f}]"
            if interaction
            else "insufficient overlap"
        )
        lines.append(
            f"| {row['hero']} | {row['landmark_s'] // 60}m | {row['fold']} | {raw} | {result['overlap_group_counts'][3]} | {difference} | {value} |"
        )
    lines += ["", "## Screened candidates", ""]
    for row in report["discoveries"]:
        train = row["train"]["adjusted"]["interaction"]
        val = row["validation"]["adjusted"]
        lines += [
            f"- **{row['hero']}: {row['first']} + {row['second']}** — training interaction {train['difference'] * 100:+.1f} pp; adjusted q={row['train_interaction_q']:.4g}. "
            + (
                f"Validation interaction {val['interaction']['difference'] * 100:+.1f} pp; "
                if val
                else "Insufficient validation overlap; "
            )
            + f"replicated after correction: {row['replicated_negative_interaction']}.",
        ]
    lines += [
        "",
        "## Interpretation",
        "",
        "No pair is automatically banned. Full other-item inventory, player skill, enemy composition, and build intent can still confound these contrasts. Standard errors are approximate and conditional on the estimated common-stratum weights.",
        "Co-admission identifies plausible candidate pairs; it does not assign a historical player to a final build. Core identity is not used as a future-derived adjustment variable.",
        "The fixed build pools already used release evidence, including later-fold checks. This chronological comparison is exploratory, not a fresh untouched holdout. Test-fold match rows are not loaded by this screen.",
        "A follow-up purchase study should compare buying the second item with legal alternatives at the same pre-purchase opportunity, given that the first item is already owned. That is closer to the actual recommendation decision.",
        "See [structured results](report.json) and [frozen data/protocol](data-manifest.json).",
        "",
    ]
    (output / "REPORT.md").write_text("\n".join(lines))


def run(directory: Path) -> None:
    manifest = json.loads((directory / "data-manifest.json").read_text())
    if fingerprint(directory / "landmarks.parquet") != manifest["landmarks_sha256"]:
        raise ValueError("Frozen landmark data changed")
    source = Path(manifest["source"])
    pools, _ = load_pools(Path(manifest["evidence_path"]), source)
    catalog = Catalog(source)
    data = read_arrays(directory)
    results = screen(data, pools, catalog)
    discoveries = replicate(results, data)
    report = {
        "candidate_pairs": len(results),
        "estimable_pairs": sum(row["train"]["adjusted"] is not None for row in results),
        "discoveries": discoveries,
        "replications": sum(
            row["replicated_negative_interaction"] for row in discoveries
        ),
        "requested_pair": requested_pair(data),
        "promotion": False,
        "causal_claim": False,
        "source_manifest_sha256": fingerprint(directory / "data-manifest.json"),
        "script_sha256": fingerprint(Path(__file__)),
    }
    (directory / "all-pairs.json").write_text(json.dumps(results, indent=2) + "\n")
    (directory / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    render(report, directory)
    print(
        json.dumps({
            key: report[key]
            for key in ("candidate_pairs", "estimable_pairs", "replications")
        })
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    args = parser.parse_args()
    run(args.directory)
