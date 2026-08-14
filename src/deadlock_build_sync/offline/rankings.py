from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import duckdb
import polars as pl

from .api import read_json, write_json
from .config import RunPaths

RANKING_METHODS = {
    "event_volume": "purchase_events",
    "adoption": "adoption_rate",
    "wilson_lower": "wilson_lower",
    "empirical_bayes_mean": "eb_mean",
    "empirical_bayes_lower": "eb_lower",
    "state_adjusted_eb": "state_adjusted_eb",
    "ridge_adjusted": "ridge_adjusted_rate",
}
CORE_MIN_ACTIONS = 8
CORE_TARGET_ACTIONS = 10
CORE_MAX_ACTIONS = 12
CORE_BUDGET = 30_000
BASE_SLOTS = 9
MAX_ACTIVES = 4


def _rows_frame(rows: list[dict[str, Any]]) -> pl.DataFrame:
    return pl.DataFrame(rows, infer_schema_length=None)


def _longest_common_subsequence(first: list[int], second: list[int]) -> int:
    lengths = [[0] * (len(second) + 1) for _ in range(len(first) + 1)]
    for first_index, first_item in enumerate(first, start=1):
        for second_index, second_item in enumerate(second, start=1):
            if first_item == second_item:
                lengths[first_index][second_index] = (
                    lengths[first_index - 1][second_index - 1] + 1
                )
            else:
                lengths[first_index][second_index] = max(
                    lengths[first_index - 1][second_index],
                    lengths[first_index][second_index - 1],
                )
    return lengths[-1][-1]


@dataclass(frozen=True)
class Asset:
    item_id: int
    name: str
    class_name: str
    tier: int
    cost: int
    active: bool
    components: tuple[str, ...]


def _assets(paths: RunPaths) -> tuple[dict[int, Asset], dict[str, int]]:
    assets: dict[int, Asset] = {}
    by_class: dict[str, int] = {}
    for row in read_json(paths.raw / "items.json"):
        asset = Asset(
            item_id=int(row["id"]),
            name=str(row.get("name") or f"Item {row['id']}"),
            class_name=str(row.get("class_name") or ""),
            tier=int(row["item_tier"]),
            cost=int(row.get("cost") or 0),
            active=bool(row.get("is_active_item")),
            components=tuple(
                str(value) for value in (row.get("component_items") or [])
            ),
        )
        assets[asset.item_id] = asset
        if asset.class_name:
            by_class[asset.class_name] = asset.item_id
    return assets, by_class


def _percentile_by_tier(rows: list[dict[str, Any]], column: str) -> dict[int, float]:
    result: dict[int, float] = {}
    by_tier: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_tier[int(row["tier"])].append(row)
    for group in by_tier.values():
        ordered = sorted(
            group,
            key=lambda row: (
                float(row.get(column) or float("-inf")),
                int(row["adopter_matches"]),
                -int(row["item_id"]),
            ),
        )
        denominator = max(1, len(ordered) - 1)
        for index, row in enumerate(ordered):
            result[int(row["item_id"])] = index / denominator
    return result


def _build_path(
    hero_rows: list[dict[str, Any]],
    method: str,
    column: str,
    assets: dict[int, Asset],
    by_class: dict[str, int],
) -> dict[str, Any]:
    percentile = _percentile_by_tier(hero_rows, column)
    supported = [row for row in hero_rows if row.get(column) is not None]
    candidates = sorted(
        supported,
        key=lambda row: (
            -percentile[int(row["item_id"])],
            -float(row["adoption_rate"]),
            int(row["item_id"]),
        ),
    )
    shortlist: list[dict[str, Any]] = []
    tier_counts: dict[int, int] = defaultdict(int)
    for row in candidates:
        tier = int(row["tier"])
        if tier_counts[tier] < 4:
            shortlist.append(row)
            tier_counts[tier] += 1
    shortlist.sort(
        key=lambda row: (
            float(row.get("median_buy_time_s") or 99999),
            -percentile[int(row["item_id"])],
            int(row["item_id"]),
        )
    )

    owned: list[int] = []
    steps: list[dict[str, Any]] = []
    cash_cost = 0
    for row in shortlist:
        if len(steps) >= CORE_TARGET_ACTIONS:
            break
        item_id = int(row["item_id"])
        asset = assets[item_id]
        component_ids = tuple(
            by_class[name] for name in asset.components if name in by_class
        )
        credited = sum(assets[value].cost for value in component_ids if value in owned)
        incremental = max(0, asset.cost - credited)
        if cash_cost + incremental > CORE_BUDGET:
            continue
        post_owned = [value for value in owned if value not in component_ids]
        active_count = sum(assets[value].active for value in post_owned)
        if asset.active and active_count >= MAX_ACTIVES:
            continue
        sold_item: int | None = None
        if len(post_owned) >= BASE_SLOTS:
            sale_candidates = sorted(
                post_owned,
                key=lambda value: (
                    assets[value].tier,
                    percentile.get(value, 0.0),
                    assets[value].cost,
                ),
            )
            if not sale_candidates:
                continue
            sold_item = sale_candidates[0]
            post_owned.remove(sold_item)
        post_owned.append(item_id)
        owned = post_owned
        cash_cost += incremental
        steps.append({
            "step": len(steps) + 1,
            "item_id": item_id,
            "item_name": asset.name,
            "tier": asset.tier,
            "incremental_cost": incremental,
            "cumulative_cost": cash_cost,
            "median_buy_time_s": row.get("median_buy_time_s"),
            "observed_buy_nw_q25": row.get("buy_nw_q25"),
            "observed_buy_nw_q75": row.get("buy_nw_q75"),
            "valid_buy_nw_share": row.get("valid_buy_nw_share"),
            "method_score": row.get(column),
            "adoption_rate": row.get("adoption_rate"),
            "eb_mean": row.get("eb_mean"),
            "state_adjusted_eb": row.get("state_adjusted_eb"),
            "ridge_adjusted_rate": row.get("ridge_adjusted_rate"),
            "sold_item_id": sold_item,
            "sold_item_name": assets[sold_item].name if sold_item else None,
        })
    legal = (
        CORE_MIN_ACTIONS <= len(steps) <= CORE_MAX_ACTIONS
        and cash_cost <= CORE_BUDGET
        and len(owned) <= BASE_SLOTS
        and sum(assets[value].active for value in owned) <= MAX_ACTIVES
    )
    return {
        "method": method,
        "score_column": column,
        "legal": legal,
        "actions": len(steps),
        "cumulative_cost": cash_cost,
        "final_owned_items": owned,
        "steps": steps,
    }


def _poisson_binomial_tail(probabilities: list[float], minimum: int) -> float:
    distribution = [1.0, *([0.0] * len(probabilities))]
    for probability in probabilities:
        for successes in range(len(probabilities), 0, -1):
            distribution[successes] = (
                distribution[successes] * (1 - probability)
                + distribution[successes - 1] * probability
            )
        distribution[0] *= 1 - probability
    return sum(distribution[minimum:])


def _path_coherence(
    con: duckdb.DuckDBPyConnection, paths_json: list[dict[str, Any]]
) -> tuple[pl.DataFrame, pl.DataFrame]:
    adoption_paths = [path for path in paths_json if path["method"] == "adoption"]
    path_items = pl.DataFrame(
        [
            {"hero_id": int(path["hero_id"]), "item_id": int(step["item_id"])}
            for path in adoption_paths
            for step in path["steps"]
        ],
        schema={"hero_id": pl.Int64, "item_id": pl.Int64},
    )
    path_summary = pl.DataFrame([
        {
            "hero_id": int(path["hero_id"]),
            "hero_name": str(path["hero_name"]),
            "path_actions": int(path["actions"]),
            "path_cost": int(path["cumulative_cost"]),
            "independent_share_with_six": _poisson_binomial_tail(
                [float(step["adoption_rate"]) for step in path["steps"]], 6
            ),
            "independent_share_with_eight": _poisson_binomial_tail(
                [float(step["adoption_rate"]) for step in path["steps"]], 8
            ),
            "independent_share_complete": _poisson_binomial_tail(
                [float(step["adoption_rate"]) for step in path["steps"]],
                int(path["actions"]),
            ),
        }
        for path in adoption_paths
    ])
    con.register("adoption_path_items", path_items)
    con.register("adoption_path_summary", path_summary)
    match_coverage = con.sql(
        """
        SELECT pm.hero_id, pm.match_id, pm.player_slot, f.fold, pm.duration_s,
               pm.final_net_worth, s.hero_name, s.path_actions, s.path_cost,
               s.independent_share_with_six,
               s.independent_share_with_eight,
               s.independent_share_complete,
               count(DISTINCT pi.item_id) FILTER (
                   WHERE fp.item_id IS NOT NULL
               ) AS path_items_bought
        FROM player_matches pm
        JOIN match_folds f USING (match_id)
        JOIN adoption_path_summary s USING (hero_id)
        LEFT JOIN first_purchases fp
          ON pm.match_id = fp.match_id AND pm.player_slot = fp.player_slot
        LEFT JOIN adoption_path_items pi
          ON fp.hero_id = pi.hero_id AND fp.item_id = pi.item_id
        GROUP BY ALL
        """
    ).pl()
    con.register("path_match_coverage", match_coverage)
    overall = con.sql(
        """
        SELECT hero_id, any_value(hero_name) AS hero_name,
               any_value(path_actions) AS path_actions,
               any_value(path_cost) AS path_cost, count(*) AS player_matches,
               avg(path_items_bought) AS mean_path_items_bought,
               median(path_items_bought) AS median_path_items_bought,
               quantile_cont(path_items_bought, 0.25) AS path_items_q25,
               quantile_cont(path_items_bought, 0.75) AS path_items_q75,
               avg(path_items_bought::DOUBLE / path_actions) AS mean_path_coverage,
               avg((path_items_bought >= 4)::INTEGER) AS share_with_four,
               avg((path_items_bought >= 6)::INTEGER) AS share_with_six,
               avg((path_items_bought >= 8)::INTEGER) AS share_with_eight,
               avg((path_items_bought = path_actions)::INTEGER) AS share_complete,
               any_value(independent_share_with_six) AS independent_share_with_six,
               avg((path_items_bought >= 6)::INTEGER)
                   / any_value(independent_share_with_six) AS six_item_coherence_lift,
               any_value(independent_share_with_eight) AS independent_share_with_eight,
               avg((path_items_bought >= 8)::INTEGER)
                   / any_value(independent_share_with_eight) AS eight_item_coherence_lift,
               any_value(independent_share_complete) AS independent_share_complete,
               avg((path_items_bought = path_actions)::INTEGER)
                   / any_value(independent_share_complete) AS complete_coherence_lift,
               count(*) FILTER (WHERE duration_s >= 2100) AS long_matches,
               avg((path_items_bought >= 6)::INTEGER) FILTER (
                   WHERE duration_s >= 2100
               ) AS long_match_share_with_six,
               avg((path_items_bought >= 8)::INTEGER) FILTER (
                   WHERE duration_s >= 2100
               ) AS long_match_share_with_eight,
               count(*) FILTER (
                   WHERE final_net_worth >= path_cost
               ) AS affordable_matches,
               avg((path_items_bought >= 6)::INTEGER) FILTER (
                   WHERE final_net_worth >= path_cost
               ) AS affordable_share_with_six,
               avg((path_items_bought >= 8)::INTEGER) FILTER (
                   WHERE final_net_worth >= path_cost
               ) AS affordable_share_with_eight
        FROM path_match_coverage GROUP BY hero_id ORDER BY hero_id
        """
    ).pl()
    temporal = con.sql(
        """
        SELECT hero_id, any_value(hero_name) AS hero_name, fold,
               count(*) AS player_matches,
               avg(path_items_bought::DOUBLE / path_actions) AS mean_path_coverage,
               avg((path_items_bought >= 6)::INTEGER) AS share_with_six,
               avg((path_items_bought >= 8)::INTEGER) AS share_with_eight,
               avg((path_items_bought = path_actions)::INTEGER) AS share_complete
        FROM path_match_coverage
        GROUP BY hero_id, fold ORDER BY hero_id, fold
        """
    ).pl()
    return overall, temporal


def generate_rankings(paths: RunPaths) -> dict[str, Any]:
    metrics = pl.read_csv(paths.tables / "item_metrics.csv")
    heroes = {
        int(row["id"]): str(row.get("name") or f"Hero {row['id']}")
        for row in read_json(paths.raw / "heroes.json")
    }
    ranking_rows: list[dict[str, Any]] = []
    for method, column in RANKING_METHODS.items():
        if column not in metrics.columns:
            continue
        eligible = metrics.filter(pl.col(column).is_not_null())
        for key, group in eligible.group_by(["hero_id", "tier"]):
            hero_id, tier = int(key[0]), int(key[1])
            ordered = group.sort(
                [column, "adopter_matches", "item_id"],
                descending=[True, True, False],
            ).head(10)
            for rank, row in enumerate(ordered.to_dicts(), start=1):
                ranking_rows.append({
                    "hero_id": hero_id,
                    "hero_name": heroes.get(hero_id, f"Hero {hero_id}"),
                    "tier": tier,
                    "method": method,
                    "rank": rank,
                    **row,
                })
    rankings = _rows_frame(ranking_rows)
    rankings.write_csv(paths.tables / "top10_rankings.csv")

    assets, by_class = _assets(paths)
    path_rows: list[dict[str, Any]] = []
    paths_json: list[dict[str, Any]] = []
    for hero_id, group in metrics.group_by("hero_id"):
        resolved_hero_id = int(hero_id[0])
        rows = group.to_dicts()
        for method, column in RANKING_METHODS.items():
            if column not in metrics.columns:
                continue
            path = _build_path(rows, method, column, assets, by_class)
            path["hero_id"] = resolved_hero_id
            path["hero_name"] = heroes.get(resolved_hero_id, f"Hero {resolved_hero_id}")
            paths_json.append(path)
            for step in path["steps"]:
                path_rows.append({
                    "hero_id": resolved_hero_id,
                    "hero_name": path["hero_name"],
                    "method": method,
                    "path_legal": path["legal"],
                    "path_actions": path["actions"],
                    "final_inventory_items": len(path["final_owned_items"]),
                    "path_cost": path["cumulative_cost"],
                    **step,
                })
    path_frame = _rows_frame(path_rows)
    path_frame.write_csv(paths.tables / "experimental_core_paths.csv")
    write_json(paths.tables / "experimental_core_paths.json", paths_json)

    train_metrics = pl.read_csv(paths.tables / "train_item_metrics.csv")
    test_metrics = pl.read_csv(paths.tables / "test_item_metrics.csv")
    test_by_hero = {
        int(key[0]): group for key, group in test_metrics.group_by("hero_id")
    }
    stability_rows: list[dict[str, Any]] = []
    for key, train_group in train_metrics.group_by("hero_id"):
        hero_id = int(key[0])
        test_group = test_by_hero.get(hero_id)
        if test_group is None:
            continue
        train_path = _build_path(
            train_group.to_dicts(), "adoption", "adoption_rate", assets, by_class
        )
        test_path = _build_path(
            test_group.to_dicts(), "adoption", "adoption_rate", assets, by_class
        )
        train_items = [int(step["item_id"]) for step in train_path["steps"]]
        test_items = [int(step["item_id"]) for step in test_path["steps"]]
        union = set(train_items) | set(test_items)
        prefix_matches = sum(
            first == second
            for first, second in zip(train_items, test_items, strict=False)
        )
        stability_rows.append({
            "hero_id": hero_id,
            "hero_name": heroes.get(hero_id, f"Hero {hero_id}"),
            "train_legal": bool(train_path["legal"]),
            "test_legal": bool(test_path["legal"]),
            "train_actions": len(train_items),
            "test_actions": len(test_items),
            "item_set_jaccard": (
                len(set(train_items) & set(test_items)) / len(union) if union else 0.0
            ),
            "ordered_lcs_share": (
                _longest_common_subsequence(train_items, test_items)
                / max(len(train_items), len(test_items))
                if train_items or test_items
                else 0.0
            ),
            "same_position_share": (
                prefix_matches / max(len(train_items), len(test_items))
                if train_items or test_items
                else 0.0
            ),
        })
    path_stability = _rows_frame(stability_rows)
    path_stability.write_csv(paths.tables / "core_path_stability.csv")
    with duckdb.connect(str(paths.raw / "analysis.duckdb"), read_only=True) as con:
        path_coherence, path_coherence_temporal = _path_coherence(con, paths_json)
    path_coherence.write_csv(paths.tables / "path_coherence.csv")
    path_coherence_temporal.write_csv(paths.tables / "path_coherence_temporal.csv")
    return {
        "ranking_rows": rankings.height,
        "paths": len(paths_json),
        "legal_paths": sum(bool(path["legal"]) for path in paths_json),
        "path_stability_rows": path_stability.height,
        "path_coherence_rows": path_coherence.height,
        "path_coherence_temporal_rows": path_coherence_temporal.height,
    }
