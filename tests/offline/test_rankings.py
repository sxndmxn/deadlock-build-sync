from deadlock_build_sync.offline.rankings import (
    Asset,
    _build_path,
    _longest_common_subsequence,
    _poisson_binomial_tail,
    _rows_frame,
)


def test_ranking_rows_support_unsigned_item_ids() -> None:
    frame = _rows_frame([{"item_id": 1}, {"item_id": 2**32 - 1}])

    assert frame["item_id"].to_list() == [1, 2**32 - 1]


def test_longest_common_subsequence_measures_ordered_path_overlap() -> None:
    assert _longest_common_subsequence([1, 2, 3, 4], [2, 1, 3, 5, 4]) == 3


def test_poisson_binomial_tail_matches_two_independent_items() -> None:
    assert _poisson_binomial_tail([0.5, 0.5], 1) == 0.75
    assert _poisson_binomial_tail([0.5, 0.5], 2) == 0.25


def test_experimental_path_respects_budget_slots_and_actives() -> None:
    assets = {
        item_id: Asset(
            item_id=item_id,
            name=f"Item {item_id}",
            class_name=f"item_{item_id}",
            tier=((item_id - 1) % 4) + 1,
            cost=(800, 1600, 3200, 6400)[(item_id - 1) % 4],
            active=item_id in {4, 8, 12, 16},
            components=(),
        )
        for item_id in range(1, 17)
    }
    rows = [
        {
            "item_id": item_id,
            "tier": asset.tier,
            "adopter_matches": 1000 - item_id,
            "adoption_rate": (1000 - item_id) / 1000,
            "purchase_events": 1200 - item_id,
            "wilson_lower": 0.5 + item_id / 1000,
            "eb_mean": 0.51 + item_id / 1000,
            "state_adjusted_eb": 0.52 + item_id / 1000,
            "ridge_adjusted_rate": 0.53 + item_id / 1000,
            "median_buy_time_s": item_id * 100,
            "buy_nw_q25": item_id * 1000,
            "buy_nw_q75": item_id * 1200,
            "valid_buy_nw_share": 0.9,
        }
        for item_id, asset in assets.items()
    ]
    path = _build_path(rows, "adoption", "adoption_rate", assets, {})
    assert 8 <= path["actions"] <= 12
    assert path["cumulative_cost"] <= 30_000
    assert len(path["final_owned_items"]) <= 9
    assert sum(assets[item].active for item in path["final_owned_items"]) <= 4
