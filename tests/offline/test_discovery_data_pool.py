from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import duckdb
import numpy as np
import pytest

from deadlock_build_sync.mechanics import ItemGraph
from deadlock_build_sync.offline import discovery_artifacts, discovery_data
from deadlock_build_sync.offline.discovery_data import build_hero_discovery_data
from deadlock_build_sync.offline.discovery_orders import select_purchase_order
from deadlock_build_sync.offline.discovery_pool import (
    calculate_purchase_timing_policy,
    estimate_purchase_placement,
    summarize_purchase_evidence,
)
from tests.build_evidence_fixtures import make_item_assets
from tests.offline.discovery_fixtures import (
    make_discovery_catalog,
    make_hero_discovery_data,
    make_item_graph,
)
from tests.offline.sql_fixtures import load_fixture_sql

if TYPE_CHECKING:
    from pathlib import Path

    from deadlock_build_sync.offline.discovery_types import (
        FirstPurchaseRow,
        HeroLandmarkRow,
        NominatedCoreBuild,
    )


def test_whole_match_time_partitions_and_reserved_test_exclusion() -> None:
    connection = duckdb.connect()
    connection.execute(load_fixture_sql("partitions/create_player_matches.sql"))
    connection.execute(load_fixture_sql("partitions/create_match_folds.sql"))
    discovery_data.prepare_discovery_partitions(connection)
    rows = connection.execute(
        load_fixture_sql("select_discovery_partitions.sql")
    ).fetchall()
    assert rows == [
        (
            index,
            "discovery" if index < 6 else "selection" if index < 8 else "validation",
        )
        for index in range(9)
    ]
    assert len({row[0] for row in rows}) == len(rows)
    connection.close()


def test_inventory_reconstruction_uses_sales_consumption_rebuys_and_latest_time() -> (
    None
):
    graph = make_item_graph()
    graph.nodes[1] = replace(graph.nodes[1], component_classes=("item0",), cost=3200)
    graph = ItemGraph(graph.nodes)
    rows: list[HeroLandmarkRow] = [
        (index, 0, "discovery", True, 15000, 0, 90, 1, [1, 2, 3, 4, 5, 6])
        for index in range(100)
    ]
    histories = {
        (index, 0): [(0, 10, 0), (1, 20, 50), (0, 30, 0), (2, 40, 45), (1, 60, 0)]
        for index in range(100)
    }
    data = build_hero_discovery_data(7, rows, histories, graph)
    assert data.items == (1,)
    assert data.matrix.all()
    assert (data.times == 60).all()
    assert set(data.inventories) == {(1,)}
    with pytest.raises(ValueError, match="duplicate hero appearances"):
        build_hero_discovery_data(7, rows + rows[:1], histories, graph)
    empty = build_hero_discovery_data(7, [], {}, graph)
    assert empty.matrix.shape == (0, 0)


def test_missing_hero_source_is_an_error() -> None:
    connection = duckdb.connect()
    connection.execute(load_fixture_sql("partitions/create_empty_player_matches.sql"))
    with pytest.raises(ValueError, match="no source data; run refresh-evidence"):
        discovery_data.load_hero_discovery_data(connection, 7, make_item_graph())
    connection.close()


def test_pool_counts_first_buyers_and_fresh_wealth_without_outcomes() -> None:
    rows: list[FirstPurchaseRow] = [
        (index, 0, 103, 200, 5000, 100) for index in range(20)
    ]
    rows += [(index, 0, 104, 300, None, None) for index in range(19)]
    evidence = summarize_purchase_evidence(rows, 100)
    priorities, bounds = calculate_purchase_timing_policy(evidence["items"])
    assert bounds == {103: (5000, 5000)}
    assert priorities[104][0] == float("inf")
    assert evidence["items"][103]["adoption"] == 0.2
    graph = ItemGraph.from_assets(make_item_assets())
    pool = discovery_artifacts.select_tier_item_pool(graph, evidence, ())
    assert pool == {"1": [103], "2": [], "3": [], "4": []}
    with pytest.raises(ValueError, match="duplicate player/item"):
        summarize_purchase_evidence(rows + rows[:1], 100)
    with pytest.raises(ValueError, match="exceeds"):
        summarize_purchase_evidence(rows, 1)
    stale = summarize_purchase_evidence(
        [(0, 0, 103, 200, 5000, 200), (1, 0, 103, 500, 5000, 199)], 2
    )
    assert stale["items"][103]["fresh_wealth_observations"] == 0


def test_unknown_timing_keeps_options_and_does_not_order_ties() -> None:
    rows: list[FirstPurchaseRow] = [
        (index, 0, item, time, 5000, time - 1)
        for index in range(20)
        for item, time in ((101, 100), (103, 200), (102, 300))
    ]
    evidence = summarize_purchase_evidence(rows, 100)
    assert estimate_purchase_placement(103, [101, 102], evidence)["after_step"] == 1
    for history in evidence["histories"].values():
        history[103] = 100
    assert estimate_purchase_placement(103, [101, 102], evidence)["after_step"] is None
    assert estimate_purchase_placement(103, [], evidence)["after_step"] is None
    evidence["histories"][100, 0] = {103: 100}
    assert estimate_purchase_placement(103, [101, 102], evidence)["support"] == 0


def test_order_selection_requires_supported_full_order_and_mechanics() -> None:
    data = make_hero_discovery_data()
    good = select_purchase_order(data, [0, 1, 2, 3], "pairwise", make_item_graph())
    assert good["admitted_before_validation"]
    tied = replace(data, times=np.where(data.matrix, 100, -1))
    assert not select_purchase_order(tied, [0, 1, 2, 3], "pairwise", make_item_graph())[
        "admitted_before_validation"
    ]
    assert not select_purchase_order(
        data, [0, 1, 2, 3], "pairwise", make_item_graph(count=3)
    )["legal"]
    assert make_discovery_catalog(4)["3"]["cost"] == 1600


def test_exact_core_pool_uses_only_discovery_owners(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = make_hero_discovery_data()
    data.actors = tuple((int(match), 0) for match in data.matches)
    owners = discovery_artifacts.select_core_owners(data, [0, 1, 2, 3], "discovery")
    assert len(owners) == 400
    assert all(match < 1200 for match, _ in owners)
    combined = discovery_artifacts.select_core_owners(data, [0, 1, 2, 3])
    assert len(combined) == 800
    assert all(match < 1200 or match >= 2400 for match, _ in combined)
    row: NominatedCoreBuild = {"items": [0, 1, 2, 3], "path": {"order": []}}
    monkeypatch.setattr(
        discovery_artifacts,
        "load_item_pool_evidence",
        lambda *_args: summarize_purchase_evidence([], 400),
    )
    connection = duckdb.connect()
    assert not discovery_artifacts.freeze_purchase_guide(
        connection, data, row, make_item_graph()
    )["ready"]
    row["path"]["order"] = [0, 1, 2, 3]
    assert "Incomplete component purchase records" in str(
        discovery_artifacts.freeze_purchase_guide(
            connection, data, row, make_item_graph()
        )["reason"]
    )
    connection.close()


@pytest.mark.parametrize(("hero", "slot", "expected_time"), [(7, 0, 100), (8, 1, 50)])
def test_pool_sql_preserves_first_purchase_in_exact_membership(
    tmp_path: Path, hero: int, slot: int, expected_time: int
) -> None:
    connection = duckdb.connect(str(tmp_path / "pool.duckdb"))
    connection.execute(load_fixture_sql("pool/create_purchases.sql"))
    connection.execute(load_fixture_sql("pool/insert_purchase_history.sql"))
    evidence = discovery_artifacts.load_item_pool_evidence(
        connection, frozenset({(1, slot)}), hero
    )
    assert evidence["population"] == 1
    assert evidence["histories"] == {(1, slot): {101: float(expected_time)}}
    connection.close()
