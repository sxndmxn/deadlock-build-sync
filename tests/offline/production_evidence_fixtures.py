import duckdb
import polars as pl

from deadlock_build_sync.mechanics import ItemGraph
from deadlock_build_sync.value_validation import (
    require_object_dict,
    require_object_rows,
)


def _candidate_sample(policy: dict[str, object]) -> list[dict[str, object]]:
    audit = require_object_dict(policy["candidate_audit"])
    return require_object_rows(audit["sample"])


def _item_metric_row() -> dict[str, object]:
    return {
        "item_id": 101,
        "item_name": "Compress Cooldown",
        "tier": 3,
        "cost": 3200,
        "slot": "spirit",
        "active": False,
        "adopter_matches": 100,
        "selection_adopter_matches": 100,
        "training_adopter_matches": 50,
        "validation_adopter_matches": 50,
        "test_adopter_matches": 0,
        "hero_player_matches": 200,
        "purchase_events": 105,
        "wins": 55,
        "adoption_rate": 0.5,
        "raw_outcome_rate": 0.55,
        "median_buy_time_s": 900.0,
        "median_valid_buy_net_worth": 12_000.0,
        "buy_nw_q25": 10_000.0,
        "buy_nw_q75": 14_000.0,
        "valid_buy_nw_share": 0.95,
        "selection_median_buy_time_s": 900.0,
        "selection_median_valid_buy_net_worth": 12_000.0,
        "selection_buy_nw_q25": 10_000.0,
        "selection_buy_nw_q75": 14_000.0,
        "selection_valid_buy_nw_observations": 100,
        "training_valid_buy_nw_observations": 50,
        "validation_valid_buy_nw_observations": 50,
        "training_buy_nw_q25": 10_000.0,
        "training_buy_nw_q75": 14_000.0,
        "validation_buy_nw_q25": 10_000.0,
        "validation_buy_nw_q75": 14_000.0,
        "imbued_ability_id": 40,
        "target_matches": 75,
        "imbue_observations": 100,
        "target_share": 0.75,
    }


def _contrast_rows(*, positive: bool) -> list[dict[str, object]]:
    return [
        {
            "match_id": index + 1,
            "player_slot": 0,
            "fold": ("train", "validation", "test")[index // 800],
            "item_id": 10 if index % 2 == 0 else 20,
            "won": int(index % 2 == 0) if positive else (index // 2) % 2,
            "average_badge": 90,
            "phase": 2,
            "buy_time": 1_200,
            "own_net_worth_at_buy": 20_000,
            "state_observed_at_s": 1_190,
            "own_team_net_worth": 100_000,
            "enemy_team_net_worth": 100_000,
            "team_net_worth_lead": 0,
            "state_age_s": 10,
            "prior_catalog_spend": 18_000,
            "prior_purchase_count": 6,
        }
        for index in range(2_400)
    ]


def _item_graph(components: dict[int, tuple[int, ...]]) -> ItemGraph:
    return ItemGraph.from_assets([
        {
            "id": item_id,
            "class_name": f"item_{item_id}",
            "name": f"Item {item_id}",
            "cost": 800,
            "item_slot_type": "weapon",
            "item_tier": 1,
            "component_items": [
                f"item_{component_id}" for component_id in components.get(item_id, ())
            ],
            "shopable": True,
            "disabled": False,
            "is_active_item": False,
            "is_unique": True,
        }
        for item_id in range(1, 10)
    ])


def _register_situational_tables(con: duckdb.DuckDBPyConnection) -> None:
    decisions: list[dict[str, object]] = []
    enemies: list[dict[str, object]] = []
    compositions: list[dict[str, object]] = []
    match_id = 1
    for fold in ("train", "validation", "test"):
        for item_id in (3, 4):
            for offset in range(200):
                target = item_id == 3
                won = offset < (180 if target else 40)
                decisions.append({
                    "match_id": match_id,
                    "player_slot": 0,
                    "hero_id": 12,
                    "phase": 1,
                    "tier": 2,
                    "item_id": item_id,
                    "won": won,
                    "team_id": 0,
                    "assigned_lane": 1,
                    "fold": fold,
                    "own_net_worth_at_buy": 10_000,
                    "team_net_worth_lead": 0,
                })
                enemies.append({
                    "match_id": match_id,
                    "team_id": 1,
                    "assigned_lane": 1,
                    "hero_id": 7,
                })
                compositions.append({
                    "match_id": match_id,
                    "team_id": 1,
                    "hero_ids": [7],
                })
                match_id += 1
    con.register("decisions_source", pl.DataFrame(decisions))
    con.register("enemies_source", pl.DataFrame(enemies))
    con.register("compositions_source", pl.DataFrame(compositions))
    con.execute("CREATE TABLE decision_opportunities AS SELECT * FROM decisions_source")
    con.execute("CREATE TABLE player_matches AS SELECT * FROM enemies_source")
    con.execute("CREATE TABLE compositions AS SELECT * FROM compositions_source")
