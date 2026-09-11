from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import duckdb
import polars as pl
import pytest

from deadlock_build_sync.offline import production_sources as sources
from deadlock_build_sync.offline.api import write_json
from deadlock_build_sync.offline.config import RunPaths, sha256_json
from tests.offline.sql_fixtures import load_fixture_sql

if TYPE_CHECKING:
    from pathlib import Path


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

    patch = sources._select_patch_at_timestamp(paths, datetime(2026, 8, 2, tzinfo=UTC))

    assert patch["title"] == "Old"
    assert patch["guid"] == '{"id":1}'
    assert len(str(patch["identity"])) == 64
    assert sha256_json(patch) == (
        "6e746befc32de3d8dac343b1735daeef000215306c074aa8588634442e839d64"
    )
    assert sources._normalize_patch_guid(" value ") == "value"
    assert sources._normalize_patch_guid(1) == "unknown"
    first = sources._calculate_patch_content_sha256(
        "https://clan.akamai.steamstatic.com/image.png"
    )
    second = sources._calculate_patch_content_sha256(
        "https://clan.fastly.steamstatic.com/image.png"
    )
    assert first == second


def test_patch_and_rank_sources_reject_invalid_or_future_data(tmp_path: Path) -> None:
    paths = RunPaths.create(tmp_path, "bad-patch")
    write_json(paths.raw / "patches.json", {})
    with pytest.raises(RuntimeError, match="patch list"):
        sources._select_patch_at_timestamp(paths, datetime(2026, 8, 2, tzinfo=UTC))

    write_json(
        paths.raw / "patches.json",
        [{"pub_date": "2026-08-03T00:00:00+00:00"}],
    )
    with pytest.raises(RuntimeError, match="frozen as-of"):
        sources._select_patch_at_timestamp(paths, datetime(2026, 8, 2, tzinfo=UTC))

    write_json(
        paths.raw / "ranks.json",
        [
            {"tier": 2, "name": " Oracle "},
            {"tier": "bad", "name": "Ignored"},
            {"tier": 3, "name": ""},
        ],
    )
    assert len(sources._calculate_rank_labels_sha256(paths)) == 64


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
            "duration_s": 1200,
            "own_net_worth_at_buy": 10_000 + match_id,
            "imbued_ability_id": 40 if match_id <= 15 else 0,
        }
        for match_id in range(1, 21)
    ]
    purchases = pl.DataFrame([
        {
            "match_id": row["match_id"],
            "player_slot": 0,
            "item_id": 10,
            "hero_id": row["hero_id"],
            "buy_time": row["buy_time"],
            "duration_s": row["duration_s"],
        }
        for row in rows
    ])
    connection = duckdb.connect()
    try:
        connection.register("first_source", pl.DataFrame(rows))
        connection.register("events_source", purchases)
        connection.execute(load_fixture_sql("item_metrics/create_first_purchases.sql"))
        connection.execute(load_fixture_sql("item_metrics/create_purchases.sql"))

        metrics = sources._query_path_item_metrics(
            connection,
            frozenset((match_id, 0) for match_id in range(1, 21)),
            7,
        )
    finally:
        connection.close()

    row = metrics.row(0, named=True)
    assert row["adopter_matches"] == 20
    assert row["selection_adopter_matches"] == 20
    assert row["target_matches"] == 15
    assert row["target_share"] == 1.0
