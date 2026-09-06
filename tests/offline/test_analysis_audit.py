from __future__ import annotations

from typing import TYPE_CHECKING

import duckdb
import polars as pl
import pytest

from deadlock_build_sync.offline.api import write_json
from deadlock_build_sync.offline.config import RunPaths, sha256_json
from tools.comparisons.legacy.analysis_audit import (
    _ability_scaling_signals,
    _account_breadth_stability,
    _api_audit,
    _duration_profiles,
    _effective_scale_function,
    _item_mechanics_rows,
    _match_bootstrap_intervals,
    _mechanics_audit,
)

if TYPE_CHECKING:
    from pathlib import Path


def _audit_connection() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    purchases = pl.DataFrame({
        "hero_id": [1, 1, 1, 1],
        "item_id": [10, 10, 11, 12],
        "item_purchase_ordinal": [1, 2, 1, 1],
    })
    first_purchases = pl.DataFrame({
        "hero_id": [1, 1, 1],
        "item_id": [10, 11, 12],
        "phase": [0, 1, 1],
        "own_net_worth_at_buy": [None, 8_000, 9_000],
    })
    accounts = pl.DataFrame({"hero_id": [1], "unique_accounts": [100]})
    con.register("purchases_source", purchases)
    con.register("first_purchases_source", first_purchases)
    con.register("accounts_source", accounts)
    con.execute("CREATE TABLE purchases AS SELECT * FROM purchases_source")
    con.execute("CREATE TABLE first_purchases AS SELECT * FROM first_purchases_source")
    con.execute("CREATE TABLE hero_account_counts AS SELECT * FROM accounts_source")
    return con


def _metrics() -> pl.DataFrame:
    return pl.DataFrame([
        {
            "hero_id": 1,
            "tier": 1,
            "item_id": item_id,
            "adopter_matches": 100,
            "adoption_rate": adoption,
            "raw_outcome_rate": outcome,
        }
        for item_id, adoption, outcome in (
            (10, 0.8, 0.6),
            (11, 0.6, 0.5),
            (12, 0.4, 0.4),
        )
    ])


def _write_api_audit_files(paths: RunPaths) -> None:
    write_json(
        paths.api / "hero-1-item-stats.json",
        [
            {
                "item_id": item_id,
                "matches": matches,
                "players": players,
                "wins": wins,
                "avg_buy_time_s": 600,
            }
            for item_id, matches, players, wins in (
                (10, 80, 70, 48),
                (11, 60, 50, 30),
                (12, 40, 30, 16),
            )
        ],
    )
    write_json(
        paths.api / "hero-1-item-flow-stats.json",
        {
            "nodes": [
                {
                    "item_id": 10,
                    "column": 0,
                    "matches": 80,
                    "players": 70,
                    "adjusted_win_rate": 0.55,
                    "avg_net_worth_at_buy": 1_000,
                },
                {
                    "item_id": 11,
                    "column": 1,
                    "matches": 60,
                    "players": 50,
                    "adjusted_win_rate": 0.5,
                    "avg_net_worth_at_buy": 8_200,
                },
            ]
        },
    )


def _write_mechanics_assets(paths: RunPaths) -> None:
    write_json(
        paths.raw / "items.json",
        [
            {
                "id": 10,
                "name": "Item",
                "item_tier": 1,
                "item_slot_type": "weapon",
                "cost": 500,
                "is_active_item": True,
                "properties": {"damage": 1},
                "component_items": ["component"],
                "description": "Text",
            }
        ],
    )
    ability = {
        "class_name": "ability_one",
        "name": "Ability One",
        "description": {"quip": "Quip"},
        "properties": {
            "damage": {
                "value": "1",
                "scale_function": {
                    "class_name": "scale_tech_damage",
                    "specific_stat_scale_type": "duration",
                    "scaling_stats": ["radius", "cooldown"],
                    "stat_scale": 0.5,
                },
            },
            "sentinel": {"value": "0", "scale_function": {}},
        },
    }
    write_json(paths.raw / "items-all.json", [ability])
    write_json(
        paths.raw / "heroes.json",
        [
            {
                "id": 1,
                "name": "Hero",
                "items": {
                    "signature1": "ability_one",
                    "signature2": "missing_ability",
                },
            }
        ],
    )


def test_duration_bootstrap_and_api_audits(tmp_path: Path) -> None:
    paths = RunPaths.create(tmp_path, "audit")
    write_json(
        paths.api / "hero-duration-under-25m.json",
        [
            {"hero_id": 1, "matches": 30, "wins": 18},
            {"hero_id": 2, "matches": 10, "wins": 8},
            {"hero_id": "bad", "matches": 30, "wins": 15},
        ],
    )
    _write_api_audit_files(paths)
    con = _audit_connection()
    try:
        events, flow = _api_audit(paths, con)
    finally:
        con.close()

    durations = _duration_profiles(paths)
    bootstrap = _match_bootstrap_intervals(_metrics())
    breadth = _account_breadth_stability(_metrics(), events)

    assert durations.row(0, named=True)["duration_bucket"] == "<25m"
    assert durations["ending_outcome_rate"].item() == 0.6
    assert bootstrap.height == 3
    assert bootstrap["bootstrap_replicates"].to_list() == [500] * 3
    assert events["api_account_breadth"].null_count() == 0
    assert flow.height == 2
    assert breadth["top10_jaccard"].item() == 1.0


def test_audits_work_without_optional_api_files(tmp_path: Path) -> None:
    paths = RunPaths.create(tmp_path, "no-api")
    con = _audit_connection()
    try:
        events, flow = _api_audit(paths, con)
    finally:
        con.close()

    assert events.columns == [
        "hero_id",
        "item_id",
        "raw_purchase_events",
        "raw_first_purchase_matches",
    ]
    assert flow.height == 3
    assert _duration_profiles(paths).is_empty()
    assert _account_breadth_stability(
        _metrics().head(2),
        pl.DataFrame({
            "hero_id": [1, 1],
            "item_id": [10, 11],
            "api_account_breadth": [0.7, 0.5],
        }),
    ).is_empty()


def test_mechanics_audit_resolves_scaling_channels(tmp_path: Path) -> None:
    paths = RunPaths.create(tmp_path, "mechanics")
    _write_mechanics_assets(paths)

    items, heroes, abilities = _mechanics_audit(paths)

    assert _item_mechanics_rows([]) == []
    assert items.row(0, named=True)["has_components"]
    assert heroes.row(0, named=True)["resolved_abilities"] == 1
    row = abilities.row(0, named=True)
    assert row["has_spirit_damage_scaling"]
    assert row["has_duration_scaling"]
    assert row["has_range_or_radius_scaling"]
    assert row["has_cooldown_or_recharge_scaling"]
    assert row["spirit_damage_coefficients"] == "0.5"
    assert (
        sha256_json({
            "items": items.to_dicts(),
            "heroes": heroes.to_dicts(),
            "abilities": abilities.to_dicts(),
        })
        == "23b7251c045b8b3e2c419493709d6c87ef0e6990ca1ff12e1b3e3f98226089ca"
    )


def test_mechanics_helpers_reject_invalid_scaling_and_assets(tmp_path: Path) -> None:
    assert _effective_scale_function(None) is None
    assert _effective_scale_function({"value": 0}) is None
    assert _effective_scale_function({"value": 1, "scale_function": "bad"}) is None
    assert _ability_scaling_signals({"properties": []}) == ([], set(), set(), [])

    paths = RunPaths.create(tmp_path, "bad-mechanics")
    write_json(paths.raw / "items.json", {})
    write_json(paths.raw / "items-all.json", [])
    write_json(paths.raw / "heroes.json", [])
    with pytest.raises(TypeError, match="not arrays"):
        _mechanics_audit(paths)


def test_duration_profile_rejects_invalid_payload(tmp_path: Path) -> None:
    paths = RunPaths.create(tmp_path, "bad-duration")
    write_json(paths.api / "hero-duration-custom.json", {})

    with pytest.raises(TypeError, match="not an array"):
        _duration_profiles(paths)
