from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import duckdb
import polars as pl
import pytest

from deadlock_build_sync.offline import production_sources as sources
from deadlock_build_sync.offline.api import write_json
from deadlock_build_sync.offline.config import RunPaths, sha256_json
from tests.mechanics_fixtures import item

if TYPE_CHECKING:
    from pathlib import Path


def test_enemy_threat_evidence_uses_resolved_signature_mechanics() -> None:
    ability = item(10, "ability")
    ability["class_name"] = "ability_one"
    ability["description"] = {"desc": "Gain Weapon Damage."}
    heroes: list[dict[str, object]] = [
        {"id": 1, "items": {"signature1": "ability_one", "other": 2}},
        {"id": "bad", "items": {}},
        {"id": 2},
    ]

    assets: list[dict[str, object]] = [ability, {"id": 11}]
    result = sources._enemy_threat_evidence(heroes, assets)

    assert "bullet_pressure" in result[1]
    assert 2 not in result


def test_patch_helpers_normalize_guids_content_and_cutoff(tmp_path: Path) -> None:
    paths = RunPaths.create(tmp_path, "patch")
    patches = {
        "data": [
            {"title": "ignored"},
            {
                "title": "Old",
                "pub_date": "2026-08-01T00:00:00+00:00",
                "source": "steam",
                "guid": {"id": 1},
                "link": "old",
                "content": [
                    "https://clan.akamai.steamstatic.com/image.png",
                    {"body": "old"},
                ],
            },
            {
                "title": "New",
                "pub_date": "2026-08-03T00:00:00+00:00",
                "guid": " new-guid ",
                "content": "new",
            },
        ]
    }
    write_json(paths.raw / "patches.json", patches)

    patch = sources._patch_at(paths, datetime(2026, 8, 2, tzinfo=UTC))

    assert patch["title"] == "Old"
    assert patch["guid"] == '{"id":1}'
    assert len(str(patch["identity"])) == 64
    assert sha256_json(patch) == (
        "6e746befc32de3d8dac343b1735daeef000215306c074aa8588634442e839d64"
    )
    assert sources._patch_guid(" value ") == "value"
    assert sources._patch_guid(1) == "unknown"
    first = sources._patch_content_sha256(
        "https://clan.akamai.steamstatic.com/image.png"
    )
    second = sources._patch_content_sha256(
        "https://clan.fastly.steamstatic.com/image.png"
    )
    assert first == second


def test_patch_and_rank_sources_reject_invalid_or_future_data(tmp_path: Path) -> None:
    paths = RunPaths.create(tmp_path, "bad-patch")
    write_json(paths.raw / "patches.json", {})
    with pytest.raises(RuntimeError, match="patch list"):
        sources._patch_at(paths, datetime(2026, 8, 2, tzinfo=UTC))

    write_json(
        paths.raw / "patches.json",
        [{"pub_date": "2026-08-03T00:00:00+00:00"}],
    )
    with pytest.raises(RuntimeError, match="frozen as-of"):
        sources._patch_at(paths, datetime(2026, 8, 2, tzinfo=UTC))

    write_json(
        paths.raw / "ranks.json",
        [
            {"tier": 2, "name": " Oracle "},
            {"tier": "bad", "name": "Ignored"},
            {"tier": 3, "name": ""},
        ],
    )
    assert len(sources._rank_labels_sha256(paths)) == 64


def test_inventory_queries_reconstruct_final_and_early_items() -> None:
    con = duckdb.connect()
    try:
        con.execute(
            "CREATE TABLE purchases(match_id INTEGER, player_slot INTEGER, "
            "hero_id INTEGER, item_id INTEGER, buy_time INTEGER, sold_time INTEGER, "
            "event_order INTEGER)"
        )
        con.executemany(
            "INSERT INTO purchases VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (1, 0, 7, 1, 100, 0, 1),
                (1, 0, 7, 2, 200, 0, 2),
                (2, 1, 7, 3, 100, 0, 1),
            ],
        )
        con.execute(
            "CREATE TABLE first_purchases(match_id INTEGER, player_slot INTEGER, "
            "hero_id INTEGER, item_id INTEGER, own_net_worth_at_buy INTEGER, "
            "buy_time INTEGER)"
        )
        con.executemany(
            "INSERT INTO first_purchases VALUES (?, ?, ?, ?, ?, ?)",
            [(1, 0, 7, 1, 10_000, 100), (1, 0, 7, 2, 13_000, 200)],
        )

        inventories = sources._inventories_for_hero(con, 7, {2: (1,)})
        early = sources._early_inventories_for_hero(con, 7)
    finally:
        con.close()

    assert inventories == {(1, 0): (2,), (2, 1): (3,)}
    assert early == {(1, 0): (1,)}


def test_path_item_metrics_aggregate_fold_and_imbue_support() -> None:
    rows = [
        {
            "match_id": match_id,
            "player_slot": 0,
            "hero_id": 7,
            "item_id": 10,
            "item_name": "Item",
            "tier": 2,
            "cost": 1_250,
            "slot": "spirit",
            "active": False,
            "fold": "train" if match_id <= 10 else "validation",
            "won": match_id % 2 == 0,
            "buy_time": 600 + match_id,
            "own_net_worth_at_buy": 10_000 + match_id,
            "imbued_ability_id": 40 if match_id <= 15 else 0,
        }
        for match_id in range(1, 21)
    ]
    purchases = pl.DataFrame([
        {"match_id": row["match_id"], "player_slot": 0, "item_id": 10} for row in rows
    ])
    con = duckdb.connect()
    try:
        con.register("first_source", pl.DataFrame(rows))
        con.register("events_source", purchases)
        con.execute("CREATE TABLE first_purchases AS SELECT * FROM first_source")
        con.execute("CREATE TABLE purchases AS SELECT * FROM events_source")

        metrics = sources._path_item_metrics(
            con,
            frozenset((match_id, 0) for match_id in range(1, 21)),
        )
    finally:
        con.close()

    row = metrics.row(0, named=True)
    assert row["adopter_matches"] == 20
    assert row["selection_adopter_matches"] == 20
    assert row["target_matches"] == 15
    assert row["target_share"] == 1.0
