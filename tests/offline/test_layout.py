import hashlib
import json
from pathlib import Path

import polars as pl
import pytest

from deadlock_build_sync.offline.config import RunPaths, sha256_json
from deadlock_build_sync.offline.layout import (
    create_build_layout,
    render_build_layout_markdown,
    write_build_layout,
)
from deadlock_build_sync.value_validation import require_object_rows


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
    rows = require_object_rows(layout["rows"])
    tier_items = require_object_rows(rows[1]["items"])
    core_items = require_object_rows(rows[0]["items"])

    assert [row["name"] for row in rows] == [
        "CORE ITEMS",
        "TIER 1",
        "TIER 2",
        "TIER 3",
        "TIER 4",
    ]
    assert [len(require_object_rows(row["items"])) for row in rows] == [8] * 5
    assert [item["item_id"] for item in tier_items] == list(range(110, 102, -1))
    assert [item["item_id"] for item in core_items] == [
        102,
        101,
        202,
        201,
        302,
        301,
        402,
        401,
    ]
    assert all(
        not item["core"]
        for row in rows[1:]
        for item in require_object_rows(row["items"])
    )
    assert rows[0]["optional"] is False
    assert all(row["optional"] for row in rows[1:])

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


def test_write_build_layout_writes_complete_json_and_markdown(tmp_path: Path) -> None:
    paths = RunPaths.create(tmp_path, "run")
    stem = "late_game_hero_13_45000"
    (paths.tables / f"{stem}.json").write_text(
        json.dumps(_late_game()),
        encoding="utf-8",
    )
    _items().write_csv(paths.tables / f"{stem}_items.csv")

    json_path, markdown_path = write_build_layout(
        paths,
        hero_id=13,
        hero_name="Lady Geist",
        minimum_net_worth=45_000,
    )

    assert json_path == paths.run / "builds/lady-geist-45000-plus.json"
    assert markdown_path == paths.run / "builds/lady-geist-45000-plus.md"
    assert sha256_json(json.loads(json_path.read_text(encoding="utf-8"))) == (
        "9d0509d149d1f874791b77e0c1ea105e04b96be4a7b0c68883036716d1a46851"
    )
    assert hashlib.sha256(markdown_path.read_bytes()).hexdigest() == (
        "4cba3fdbf902bd862081ae5650254e36ec450d7a4e6ff63dcbe50e7b7d025215"
    )
