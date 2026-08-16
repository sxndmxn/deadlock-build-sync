from pathlib import Path

import duckdb
import polars as pl

from deadlock_build_sync.mechanics import ItemGraph
from deadlock_build_sync.offline.config import RunPaths
from deadlock_build_sync.offline.production_evidence import (
    _duplicate_free_core_candidates,
    _expanded_default_path,
    _patch_content_sha256,
    _sequence_rows,
    _situational_policy,
    _top_core_candidates,
)


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


def test_core_candidates_are_supported_and_deterministically_ranked() -> None:
    first = tuple(range(1, 9))
    second = (*range(1, 8), 9)
    third = (*range(1, 8), 10)
    sparse = (*range(1, 8), 11)

    candidates = _top_core_candidates(
        [first] * 30 + [second] * 20 + [third] * 20 + [sparse] * 19,
        dict.fromkeys(range(1, 12), 1),
        8,
    )

    assert candidates == [
        {"item_ids": list(first), "joint_matches": 30},
        {"item_ids": list(second), "joint_matches": 20},
        {"item_ids": list(third), "joint_matches": 20},
    ]


def test_core_candidate_cap_is_applied_after_budget_filter() -> None:
    over_budget = tuple(range(1, 9))
    within_budget = (*range(1, 8), 9)

    candidates = _top_core_candidates(
        [over_budget] * 40 + [within_budget] * 30,
        {**dict.fromkeys(range(1, 10), 1), 8: 100},
        8,
    )

    assert candidates == [{"item_ids": list(within_budget), "joint_matches": 30}]


def test_patch_content_hash_normalizes_steam_cdn_routing() -> None:
    akamai = '<img src="https://clan.akamai.steamstatic.com/images/x.png">Notes'
    fastly = akamai.replace("akamai", "fastly")

    assert _patch_content_sha256(akamai) == _patch_content_sha256(fastly)
    assert _patch_content_sha256(akamai) != _patch_content_sha256(
        fastly.replace("Notes", "Changed notes")
    )


def test_component_expanded_default_path_buys_missing_components_first() -> None:
    metrics = pl.DataFrame([
        {
            "item_id": item_id,
            "median_valid_buy_net_worth": item_id * 1_000,
            "median_buy_time_s": item_id * 60,
        }
        for item_id in range(2, 10)
    ])

    path = _expanded_default_path(
        [{"item_ids": list(range(2, 10)), "joint_matches": 30}],
        metrics,
        _item_graph({2: (1,)}),
    )

    assert path == list(range(1, 10))


def test_duplicate_free_core_filter_uses_next_supported_candidate() -> None:
    metrics = pl.DataFrame([
        {
            "item_id": item_id,
            "median_valid_buy_net_worth": 1_000 if item_id == 2 else item_id * 2_000,
            "median_buy_time_s": item_id * 60,
        }
        for item_id in range(1, 10)
    ])
    candidates = [
        {"item_ids": list(range(1, 9)), "joint_matches": 30},
        {"item_ids": list(range(2, 10)), "joint_matches": 25},
    ]
    graph = _item_graph({2: (1,)})

    filtered = _duplicate_free_core_candidates(candidates, metrics, graph)
    path = _expanded_default_path(filtered, metrics, graph)

    assert filtered == [candidates[1]]
    assert path == list(range(1, 10))


def test_sequence_policy_uses_train_rows_and_emits_supported_backoffs() -> None:
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE first_purchases ("
        "match_id BIGINT, player_slot INTEGER, fold VARCHAR, hero_id INTEGER, "
        "item_id INTEGER, buy_time DOUBLE)"
    )
    con.executemany(
        "INSERT INTO first_purchases VALUES (?, ?, ?, ?, ?, ?)",
        [
            (match_id, 0, fold, 12, item_id, buy_time)
            for match_id in range(30)
            for item_id, buy_time in ((1, 10.0), (2, 20.0))
            for fold in (("train",) if match_id < 25 else ("test",))
        ],
    )

    rows = _sequence_rows(con, 12)

    assert {row["level"] for row in rows} == {
        "first_previous_position",
        "previous_position",
        "position",
        "popularity",
    }
    assert all(row["support"] >= 20 for row in rows)
    assert all(row["context_support"] >= row["support"] for row in rows)


def test_situational_candidates_are_audited_but_abstain_without_uncertainty_gate(
    tmp_path: Path,
) -> None:
    paths = RunPaths.create(tmp_path, "run")
    pl.DataFrame([
        {
            "hero_id": 12,
            "item_id": 3,
            "enemy_hero_id": 7,
            "scope": "same_lane",
            "observations": 40,
        }
    ]).write_csv(paths.tables / "matchup_interactions.csv")
    pl.DataFrame([
        {
            "hero_id": 12,
            "item_id": 3,
            "effective_support": 30.0,
            "state_coverage": 0.8,
        }
    ]).write_csv(paths.tables / "state_overlap_diagnostics.csv")
    pl.DataFrame([
        {
            "hero_id": 12,
            "scope": "same_lane",
            "spearman": 0.5,
            "sign_agreement": 0.75,
        }
    ]).write_csv(paths.tables / "matchup_temporal_stability.csv")
    assets = [{"id": 3, "description": {"desc": "Applies healing reduction."}}]

    policy = _situational_policy(paths, 12, assets)

    assert policy["branches"] == []
    assert policy["candidate_audit"][0]["threat"] == "healing"
    assert not policy["candidate_audit"][0]["gates"]["bounded_comparative_uncertainty"]
    assert policy["abstentions"]


def test_situational_branch_is_emitted_only_when_every_gate_is_present(
    tmp_path: Path,
) -> None:
    paths = RunPaths.create(tmp_path, "run")
    pl.DataFrame([
        {
            "hero_id": 12,
            "item_id": 3,
            "enemy_hero_id": 7,
            "scope": "same_lane",
            "observations": 40,
            "same_opportunity": True,
            "comparator_item_id": 4,
            "comparison_support": 30,
            "comparative_interval_low": 0.01,
            "comparative_interval_high": 0.06,
        }
    ]).write_csv(paths.tables / "matchup_interactions.csv")
    pl.DataFrame([
        {
            "hero_id": 12,
            "item_id": 3,
            "effective_support": 30.0,
            "state_coverage": 0.8,
        }
    ]).write_csv(paths.tables / "state_overlap_diagnostics.csv")
    pl.DataFrame([
        {
            "hero_id": 12,
            "scope": "same_lane",
            "spearman": 0.5,
            "sign_agreement": 0.75,
        }
    ]).write_csv(paths.tables / "matchup_temporal_stability.csv")
    assets = [
        {"id": 3, "description": {"desc": "Applies healing reduction."}},
        {"id": 4, "description": {"desc": "Plain damage."}},
    ]

    policy = _situational_policy(paths, 12, assets)

    assert len(policy["branches"]) == 1
    assert policy["branches"][0]["comparator"] == ("same-opportunity item 4 or save")
    assert policy["branches"][0]["failure_condition"]
    assert policy["candidate_audit"][0]["admitted"]
    assert policy["abstentions"] == []

    pl.DataFrame([
        {
            "hero_id": 12,
            "item_id": 3,
            "enemy_hero_id": 7,
            "scope": "same_lane",
            "observations": 40,
            "same_opportunity": True,
            "comparator_item_id": 4,
            "comparison_support": 30,
            "comparative_interval_low": -0.01,
            "comparative_interval_high": 0.06,
        }
    ]).write_csv(paths.tables / "matchup_interactions.csv")

    unsupported = _situational_policy(paths, 12, assets)

    assert unsupported["branches"] == []
    assert not unsupported["candidate_audit"][0]["gates"]["comparative_advantage"]
