import polars as pl
import pytest

from deadlock_build_sync.offline.layout import (
    create_build_layout,
    render_build_layout_markdown,
)


def _items() -> pl.DataFrame:
    rows = []
    for tier in range(1, 5):
        for index in range(1, 11):
            item_id = tier * 100 + index
            rows.append({
                "item_id": item_id,
                "item_name": f"Tier {tier} Item {index}",
                "tier": tier,
                "buyer_matches": 100 - index,
                "purchase_adoption": (100 - index) / 100,
                "final_inventory_adoption": (90 - index) / 100,
                "outcome_rate": 0.5 + index / 100,
                "median_buy_time_s": float(tier * 100 + 9 - index),
                "median_buy_net_worth": float(tier * 10_000 + 9 - index),
                "buy_nw_q25": float(tier * 10_000 + 8 - index),
                "buy_nw_q75": float(tier * 10_000 + 10 - index),
                "valid_buy_nw_share": 0.75,
            })
    return pl.DataFrame(rows)


def _late_game() -> dict[str, object]:
    return {
        "hero_id": 13,
        "minimum_final_net_worth": 45_000,
        "cohort": {
            "player_matches": 1_000,
            "median_final_net_worth": 52_000,
            "median_duration_s": 2_400,
            "outcome_rate": 0.6,
        },
        "most_common_eight_item_core": {
            "item_ids": [101, 102, 201, 202, 301, 302, 401, 402],
            "matches": 80,
            "share": 0.08,
        },
    }


def test_layout_selects_by_adoption_then_sorts_tiers_by_net_worth() -> None:
    layout = create_build_layout(_late_game(), _items(), hero_name="Haze")

    assert [row["name"] for row in layout["rows"]] == [
        "CORE ITEMS",
        "TIER 1",
        "TIER 2",
        "TIER 3",
        "TIER 4",
    ]
    assert [len(row["items"]) for row in layout["rows"]] == [8, 8, 8, 8, 8]
    assert [item["item_id"] for item in layout["rows"][1]["items"]] == list(
        range(110, 102, -1)
    )
    assert [item["item_id"] for item in layout["rows"][0]["items"]] == [
        102,
        101,
        202,
        201,
        302,
        301,
        402,
        401,
    ]
    assert all(not item["core"] for row in layout["rows"][1:] for item in row["items"])
    assert layout["rows"][0]["optional"] is False
    assert all(row["optional"] for row in layout["rows"][1:])

    markdown = render_build_layout_markdown(layout)
    assert "| **CORE ITEMS** |" in markdown
    assert "Purchase adoption" in markdown
    assert "descriptive outcome rate" in markdown
    assert "NW coverage" in markdown


def test_layout_rejects_a_four_item_core() -> None:
    late_game = _late_game()
    late_game["most_common_eight_item_core"] = {
        "item_ids": [101, 201, 301, 401],
        "matches": 100,
        "share": 0.1,
    }
    items = _items()

    with pytest.raises(ValueError, match="exactly eight"):
        create_build_layout(late_game, items, hero_name="Haze")
