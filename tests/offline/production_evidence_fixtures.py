from deadlock_build_sync.mechanics import ItemGraph
from deadlock_build_sync.offline.config import RunPaths
from deadlock_build_sync.offline.production_sources import _HeroExportContext
from tests.mechanics_fixtures import item


def _context(paths: RunPaths) -> _HeroExportContext:
    graph = ItemGraph.from_assets([
        {
            **item(item_id, f"item_{item_id}"),
            "cost": item_id * 500,
            "item_tier": item_id,
        }
        for item_id in (1, 2, 3, 4)
    ])
    assets = {item_id: item(item_id, f"item_{item_id}") for item_id in graph.nodes}
    return _HeroExportContext(
        paths=paths,
        normal_assets=list(assets.values()),
        item_graph=graph,
        mechanics_assets_by_id=assets,
        target_core_cost=3_000,
    )


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
