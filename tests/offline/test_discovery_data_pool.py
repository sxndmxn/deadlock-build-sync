from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import duckdb
import numpy as np
import pytest

from deadlock_build_sync.mechanics import ItemGraph
from deadlock_build_sync.offline import discovery_data, discovery_materialize
from deadlock_build_sync.offline.discovery_data import from_rows
from deadlock_build_sync.offline.discovery_orders import choose_order
from deadlock_build_sync.offline.discovery_pool import (
    placement,
    summarize,
    timing_policy,
)
from tests.build_evidence_fixtures import _assets
from tests.offline.discovery_fixtures import (
    catalog_fixture,
    graph_fixture,
    planted_data,
)

if TYPE_CHECKING:
    from pathlib import Path

    from deadlock_build_sync.offline.discovery_types import (
        LandmarkRow,
        Nomination,
        PurchaseRow,
    )


def test_whole_match_time_partitions_and_reserved_test_exclusion() -> None:
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE player_matches AS SELECT i//2 AS match_id, i%2 AS hero_id, i//2 AS start_time FROM range(20) t(i)"
    )
    con.execute(
        "CREATE TABLE match_folds AS SELECT i AS match_id, CASE WHEN i<8 THEN 'train' WHEN i=8 THEN 'validation' ELSE 'test' END AS fold FROM range(10) t(i)"
    )
    discovery_data.prepare_partitions(con)
    rows = con.execute(
        "SELECT * FROM discovery_partitions ORDER BY match_id"
    ).fetchall()
    assert rows == [
        (
            index,
            "discovery" if index < 6 else "selection" if index < 8 else "validation",
        )
        for index in range(9)
    ]
    assert len({row[0] for row in rows}) == len(rows)
    con.close()


def test_inventory_reconstruction_uses_sales_consumption_rebuys_and_latest_time() -> (
    None
):
    graph = graph_fixture()
    graph.nodes[1] = replace(graph.nodes[1], component_classes=("item0",), cost=3200)
    graph = ItemGraph(graph.nodes)
    rows: list[LandmarkRow] = [
        (index, 0, "discovery", True, 15000, 0, 90, 1, [1, 2, 3, 4, 5, 6])
        for index in range(100)
    ]
    histories = {
        (index, 0): [(0, 10, 0), (1, 20, 50), (0, 30, 0), (2, 40, 45), (1, 60, 0)]
        for index in range(100)
    }
    data = from_rows(7, rows, histories, graph)
    assert data.items == (1,)
    assert data.matrix.all()
    assert (data.times == 60).all()
    assert set(data.inventories) == {(1,)}
    with pytest.raises(ValueError, match="duplicate hero appearances"):
        from_rows(7, rows + rows[:1], histories, graph)
    empty = from_rows(7, [], {}, graph)
    assert empty.matrix.shape == (0, 0)


def test_missing_hero_source_is_an_error() -> None:
    con = duckdb.connect()
    con.execute("CREATE TABLE player_matches(hero_id INTEGER)")
    with pytest.raises(ValueError, match="no source data; run refresh-evidence"):
        discovery_data.load_data(con, 7, graph_fixture())
    con.close()


def test_pool_counts_first_buyers_and_fresh_wealth_without_outcomes() -> None:
    rows: list[PurchaseRow] = [(index, 0, 103, 200, 5000, 100) for index in range(20)]
    rows += [(index, 0, 104, 300, None, None) for index in range(19)]
    evidence = summarize(rows, 100)
    priorities, bounds = timing_policy(evidence["items"])
    assert bounds == {103: (5000, 5000)}
    assert priorities[104][0] == float("inf")
    assert evidence["items"][103]["adoption"] == 0.2
    graph = ItemGraph.from_assets(_assets())
    pool = discovery_materialize.item_pool(graph, evidence, ())
    assert pool == {"1": [103], "2": [], "3": [], "4": []}
    with pytest.raises(ValueError, match="duplicate player/item"):
        summarize(rows + rows[:1], 100)
    with pytest.raises(ValueError, match="exceeds"):
        summarize(rows, 1)
    stale = summarize([(0, 0, 103, 200, 5000, 200), (1, 0, 103, 500, 5000, 199)], 2)
    assert stale["items"][103]["fresh_wealth_observations"] == 0


def test_unknown_timing_keeps_options_and_does_not_order_ties() -> None:
    rows: list[PurchaseRow] = [
        (index, 0, item, time, 5000, time - 1)
        for index in range(20)
        for item, time in ((101, 100), (103, 200), (102, 300))
    ]
    evidence = summarize(rows, 100)
    assert placement(103, [101, 102], evidence)["after_step"] == 1
    for history in evidence["histories"].values():
        history[103] = 100
    assert placement(103, [101, 102], evidence)["after_step"] is None
    assert placement(103, [], evidence)["after_step"] is None
    evidence["histories"][100, 0] = {103: 100}
    assert placement(103, [101, 102], evidence)["support"] == 0


def test_order_selection_requires_supported_full_order_and_mechanics() -> None:
    data = planted_data()
    good = choose_order(data, [0, 1, 2, 3], "pairwise", graph_fixture())
    assert good["admitted_before_validation"]
    tied = replace(data, times=np.where(data.matrix, 100, -1))
    assert not choose_order(tied, [0, 1, 2, 3], "pairwise", graph_fixture())[
        "admitted_before_validation"
    ]
    assert not choose_order(data, [0, 1, 2, 3], "pairwise", graph_fixture(count=3))[
        "legal"
    ]
    assert catalog_fixture(4)["3"]["cost"] == 1600


def test_exact_core_pool_uses_only_discovery_owners(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = planted_data()
    data.actors = tuple((int(match), 0) for match in data.matches)
    owners = discovery_materialize.members_for(data, [0, 1, 2, 3], "discovery")
    assert len(owners) == 400
    assert all(match < 1200 for match, _ in owners)
    combined = discovery_materialize.members_for(data, [0, 1, 2, 3])
    assert len(combined) == 800
    assert all(match < 1200 or match >= 2400 for match, _ in combined)
    row: Nomination = {"items": [0, 1, 2, 3], "path": {"order": []}}
    monkeypatch.setattr(
        discovery_materialize, "pool_evidence", lambda *_args: summarize([], 400)
    )
    con = duckdb.connect()
    assert not discovery_materialize.freeze_guide(con, data, row, graph_fixture())[
        "ready"
    ]
    row["path"]["order"] = [0, 1, 2, 3]
    assert "Incomplete component purchase records" in str(
        discovery_materialize.freeze_guide(con, data, row, graph_fixture())["reason"]
    )
    con.close()


def test_pool_sql_preserves_first_purchase_in_exact_membership(tmp_path: Path) -> None:
    con = duckdb.connect(str(tmp_path / "pool.duckdb"))
    con.execute(
        "CREATE TABLE purchases(match_id BIGINT, player_slot INT, item_id BIGINT, buy_time INT, own_net_worth_at_buy INT, state_observed_at_s INT, duration_s INT, event_order INT)"
    )
    con.execute(
        "INSERT INTO purchases VALUES (1,0,101,100,5000,99,2000,0),(1,0,101,200,7000,199,2000,1),(2,0,101,150,6000,149,2000,0),(1,0,102,2100,9000,2099,2000,2)"
    )
    evidence = discovery_materialize.pool_evidence(con, frozenset({(1, 0)}))
    assert evidence["population"] == 1
    assert evidence["histories"] == {(1, 0): {101: 100.0}}
    con.close()
