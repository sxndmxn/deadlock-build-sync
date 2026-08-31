from __future__ import annotations

from typing import TYPE_CHECKING

import duckdb
import polars as pl
import pytest

from deadlock_build_sync.offline import rankings as rankings_module
from deadlock_build_sync.offline.api import write_json
from deadlock_build_sync.offline.config import RunPaths
from deadlock_build_sync.offline.ranking_assets import Asset

if TYPE_CHECKING:
    from pathlib import Path


def _metric_rows() -> list[dict[str, object]]:
    return [
        {
            "hero_id": 1,
            "tier": (item_id - 1) % 4 + 1,
            "item_id": item_id,
            "item_name": f"Item {item_id}",
            "adopter_matches": 100 - item_id,
            "adoption_rate": 0.9 - item_id / 100,
            "purchase_events": 110 - item_id,
            "wilson_lower": 0.7 - item_id / 100,
            "eb_mean": 0.75 - item_id / 100,
            "eb_lower": 0.65 - item_id / 100,
            "state_adjusted_eb": 0.72 - item_id / 100,
            "ridge_adjusted_rate": 0.71 - item_id / 100,
            "median_buy_time_s": item_id * 100,
            "buy_nw_q25": item_id * 500,
            "buy_nw_q75": item_id * 600,
            "valid_buy_nw_share": 0.9,
        }
        for item_id in range(1, 13)
    ]


def _write_inputs(paths: RunPaths) -> None:
    metrics = pl.DataFrame(_metric_rows())
    metrics.write_csv(paths.tables / "item_metrics.csv")
    metrics.write_csv(paths.tables / "train_item_metrics.csv")
    metrics.with_columns(
        (pl.col("adoption_rate") * 0.99).alias("adoption_rate")
    ).write_csv(paths.tables / "test_item_metrics.csv")
    write_json(paths.raw / "heroes.json", [{"id": 1, "name": "Hero"}])
    write_json(
        paths.raw / "items.json",
        [
            {
                "id": item_id,
                "name": f"Item {item_id}",
                "class_name": f"item_{item_id}",
                "item_tier": (item_id - 1) % 4 + 1,
                "cost": 500 + item_id * 10,
                "is_active_item": item_id in {1, 2, 3, 4},
                "component_items": [],
            }
            for item_id in range(1, 13)
        ],
    )
    con = duckdb.connect(str(paths.raw / "analysis.duckdb"))
    try:
        players = pl.DataFrame({
            "hero_id": [1, 1],
            "match_id": [1, 2],
            "player_slot": [0, 0],
            "duration_s": [2_000, 2_200],
            "final_net_worth": [25_000, 30_000],
        })
        folds = pl.DataFrame({"match_id": [1, 2], "fold": ["train", "test"]})
        purchases = pl.DataFrame([
            {
                "hero_id": 1,
                "match_id": match_id,
                "player_slot": 0,
                "item_id": item_id,
            }
            for match_id in (1, 2)
            for item_id in range(1, 13)
        ])
        con.register("players_source", players)
        con.register("folds_source", folds)
        con.register("purchases_source", purchases)
        con.execute("CREATE TABLE player_matches AS SELECT * FROM players_source")
        con.execute("CREATE TABLE match_folds AS SELECT * FROM folds_source")
        con.execute("CREATE TABLE first_purchases AS SELECT * FROM purchases_source")
    finally:
        con.close()


def test_generate_rankings_writes_ranks_paths_and_coherence(tmp_path: Path) -> None:
    paths = RunPaths.create(tmp_path, "rankings")
    _write_inputs(paths)

    result = rankings_module.generate_rankings(paths)

    assert result["ranking_rows"] == 84
    assert result["paths"] == 7
    assert result["legal_paths"] == 7
    assert result["path_stability_rows"] == 1
    assert result["path_coherence_rows"] == 1
    assert result["path_coherence_temporal_rows"] == 2
    assert (paths.tables / "experimental_core_paths.json").exists()


def test_post_purchase_inventory_enforces_actives_and_sells_low_value() -> None:
    assets = {
        item_id: Asset(
            item_id,
            f"Item {item_id}",
            f"item_{item_id}",
            1 if item_id == 1 else 2,
            item_id * 100,
            item_id <= 5,
            (),
        )
        for item_id in range(1, 11)
    }
    assert (
        rankings_module._post_purchase_inventory(
            [1, 2, 3, 4], assets[5], (), assets, {}
        )
        is None
    )

    passive = Asset(11, "Passive", "item_11", 4, 5_000, False, ())
    assets[11] = passive
    result = rankings_module._post_purchase_inventory(
        list(range(1, 10)),
        passive,
        (),
        assets,
        {1: 0.1},
    )
    assert result is not None
    owned, sold = result
    assert sold == 1
    assert 11 in owned
    assert len(owned) == 9


def test_path_comparison_and_stability_handle_empty_or_missing_heroes() -> None:
    empty_path: rankings_module._PathDocument = {
        "method": "adoption",
        "score_column": "adoption_rate",
        "legal": False,
        "actions": 0,
        "cumulative_cost": 0,
        "final_owned_items": [],
        "steps": [],
    }
    comparison = rankings_module._compare_core_paths(1, "Hero", empty_path, empty_path)
    assert comparison["item_set_jaccard"] == 0.0
    assert comparison["ordered_lcs_share"] == 0.0
    assert comparison["same_position_share"] == 0.0

    metrics = pl.DataFrame(_metric_rows())
    no_test = metrics.with_columns(pl.lit(2).alias("hero_id"))
    assets = {
        item_id: Asset(
            item_id,
            f"Item {item_id}",
            f"item_{item_id}",
            1,
            100,
            False,
            (),
        )
        for item_id in range(1, 13)
    }
    assert (
        rankings_module._core_path_stability_rows(
            metrics,
            no_test,
            {1: "Hero"},
            assets,
            {},
        )
        == []
    )


def test_generate_rankings_rejects_invalid_hero_assets(tmp_path: Path) -> None:
    paths = RunPaths.create(tmp_path, "bad-rankings")
    pl.DataFrame(_metric_rows()).write_csv(paths.tables / "item_metrics.csv")
    write_json(paths.raw / "heroes.json", {})

    with pytest.raises(TypeError, match="not an array"):
        rankings_module.generate_rankings(paths)
