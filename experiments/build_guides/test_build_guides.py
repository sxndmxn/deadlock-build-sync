"""Regressions for full pools, component timing, choices, and actual-inventory recovery."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import duckdb
import pytest
from deadlock_build_sync.mechanics import ItemGraph, ItemNode, MechanicsError

from experiments.build_guides.assemble import assemble, item_pool, mechanics
from experiments.build_guides.evidence import collect, placement, summarize
from experiments.build_guides.paths import Planner, covered, default_path, plan
from experiments.build_guides.render import html, markdown
from experiments.build_guides.run import replan
from experiments.qdfm.extract import fingerprint

if TYPE_CHECKING:
    from pathlib import Path


def graph_fixture() -> ItemGraph:
    specifications = {
        1: (800, 1, ()),
        2: (1600, 2, (1,)),
        3: (3200, 3, ()),
        4: (800, 1, ()),
        5: (1600, 2, (4,)),
        6: (1600, 2, ()),
        7: (6400, 4, (2,)),
        8: (1600, 2, (4,)),
        9: (1600, 2, ()),
        10: (3200, 3, (9,)),
    }
    specifications.update(dict.fromkeys(range(11, 31), (800, 1, ())))
    return ItemGraph({
        item: ItemNode(
            item,
            f"item_{item}",
            f"Item {item}",
            cost,
            "spirit",
            tier,
            tuple(f"item_{part}" for part in components),
            11 <= item <= 15,
            unique=True,
            max_count=1,
        )
        for item, (cost, tier, components) in specifications.items()
    })


def row_fixture() -> dict:
    return {
        "hero_id": 12,
        "hero": "Kelvin",
        "identity_id": "12-fixture",
        "arm": "grouped_prefixspan",
        "items": [2, 3, 5, 6],
        "names": ["Item 2", "Item 3", "Item 5", "Item 6"],
        "path": {"order": [3, 6, 5, 2]},
        "core_validation": {"win_rate": 0.61},
        "passes_core_gate": False,
        "passes_identity_gate": False,
        "passes_sequence_gate": True,
        "complete_preview": False,
        "preview_rejections": ["adjusted evidence fails family correction"],
    }


def evidence_fixture() -> dict:
    timing = {
        1: 30,
        4: 50,
        3: 100,
        6: 200,
        5: 300,
        2: 400,
        7: 900,
        8: 60,
        9: 150,
        10: 800,
    }
    timing.update({item: 1000 + item for item in range(11, 16)})
    rows = [
        (match, 1, item, time, time * 20, time - 1)
        for match in range(60)
        for item, time in timing.items()
    ]
    rows.extend((match, 1, 20, 100, 2000, 99) for match in range(19))
    return summarize(rows, 60)


def guide_fixture() -> tuple[dict, ItemGraph]:
    graph = graph_fixture()
    assets = {
        item: {"id": item, "description": {"desc": f"Effect {item}"}}
        for item in graph.nodes
    }
    return assemble(row_fixture(), graph, assets, evidence_fixture()), graph


def test_component_timing_precedes_midgame_and_core_gate_is_preserved() -> None:
    guide, _ = guide_fixture()
    assert [action["item_id"] for action in guide["default_path"]["actions"]] == [
        1,
        4,
        3,
        6,
        5,
        2,
    ]
    assert guide["default_path"]["ready"]
    assert not guide["core_path_supported"]
    assert not guide["full_policy_validated"]
    assert guide["default_path"]["actions"][-1]["cumulative_cost"] == 8000


def test_full_pool_excludes_core_and_components_and_requires_twenty_buyers() -> None:
    guide, graph = guide_fixture()
    pool = {item for items in guide["item_pool"].values() for item in items}
    assert pool == {7, 8, 9, 10, 11, 12, 13, 14, 15}
    assert pool == {card["item_id"] for card in guide["choices"]}
    evidence = evidence_fixture()
    evidence["items"].update(dict.fromkeys(range(16, 31), evidence["items"][11]))
    assert len(item_pool(graph, evidence, [1, 4])["1"]) == 10


def test_every_pool_choice_has_a_legal_path_and_explicit_position() -> None:
    guide, graph = guide_fixture()
    for card in guide["choices"]:
        branch = card["branch"]
        assert branch is not None
        state = Planner(graph, [], 0)
        spent = 0
        for action in branch["actions"]:
            state.acquire(action["item_id"], action["role"], exact=True)
            assert list(state.state.owned) == action["owned_after"]
            spent += action["incremental_cost"]
        assert spent == branch["remaining_cost"]
        assert all(
            covered(graph, item, state.state.owned) for item in guide["core_ids"]
        )
        assert card["placement"]["support"] >= 20
        assert card["triggers"]
        assert not card["passes_conditional_outcome_gate"]


def test_upgrade_consumes_core_and_shared_fork_rebuys_component() -> None:
    guide, _ = guide_fixture()
    cards = {card["item_id"]: card for card in guide["choices"]}
    upgrade = cards[7]
    assert upgrade["upgrades_core"] == [2]
    assert 2 not in upgrade["branch"]["final_inventory"]
    assert upgrade["extra_path_cost"] == 4800
    fork = cards[8]
    assert fork["rebought_components"] == [4]
    assert fork["extra_path_cost"] == 1600
    assert set(fork["branch"]["final_inventory"]) == {2, 3, 5, 6, 8}
    assert any(
        group["component"] == 4 and group["kind"] == "pick one upgrade"
        for group in guide["upgrade_groups"]
    )


def test_replan_owned_upgrades_skips_consumed_components_and_uses_liquid_cash() -> None:
    guide, graph = guide_fixture()
    result = plan(graph, guide, [], owned=[7, 5], liquid_souls=500)
    assert [step["item_id"] for step in result["actions"]] == [3, 6]
    assert result["decision"] == "save"
    assert result["save_souls"] == 2700
    assert (
        plan(graph, guide, [], owned=[7, 5, 3, 6], liquid_souls=0)["decision"]
        == "complete"
    )


def test_combining_choices_recalculates_upgrade_credit() -> None:
    guide, graph = guide_fixture()
    result = plan(graph, guide, [10, 9], liquid_souls=10000)
    purchases = [step["item_id"] for step in result["actions"]]
    assert purchases.count(9) == 1
    assert result["remaining_cost"] == 11200
    assert set(result["final_inventory"]) == {2, 3, 5, 6, 10}


def test_slots_active_limits_unknown_choices_and_duplicate_ownership_fail() -> None:
    guide, graph = guide_fixture()
    with pytest.raises(MechanicsError, match="active"):
        plan(graph, guide, [11, 12, 13, 14, 15])
    with pytest.raises(MechanicsError, match="slots"):
        plan(graph, guide, [], owned=[16, 17, 18, 19, 20, 21])
    assert (
        plan(graph, guide, [], owned=[16, 17, 18, 19, 20, 21], flex=1)["decision"]
        == "check cash"
    )
    with pytest.raises(ValueError, match="outside"):
        plan(graph, guide, [30])
    with pytest.raises(MechanicsError, match="ownership"):
        plan(graph, guide, [], owned=[7, 7])
    with pytest.raises(ValueError, match="nonnegative"):
        plan(graph, guide, [], liquid_souls=-1)


def test_rebought_component_in_current_inventory_is_valid_and_credited() -> None:
    guide, graph = guide_fixture()
    result = plan(graph, guide, [8], owned=[5, 4])
    purchase = next(step for step in result["actions"] if step["item_id"] == 8)
    assert purchase["incremental_cost"] == 800
    assert purchase["component_credit"] == 800


def test_incompatible_timing_and_missing_order_do_not_force_a_default() -> None:
    evidence = evidence_fixture()
    evidence["items"][3]["net_worth_q25_q50_q75"] = [20000, 20000, 20000]
    assert not default_path(row_fixture(), graph_fixture(), evidence)["ready"]
    row = row_fixture()
    row["path"]["order"] = []
    assert default_path(row, graph_fixture(), evidence)["actions"] == []


def test_placement_does_not_order_same_second_or_missing_anchors() -> None:
    evidence = summarize(
        [(match, 1, item, 100, 2000, 99) for match in range(20) for item in (1, 2, 3)],
        20,
    )
    result = placement(3, [1, 2], evidence)
    assert not result["supported"]
    assert result["after_step"] is None
    assert result["support"] == 0


def test_collection_reads_only_discovery_core_owners_and_first_purchases(
    tmp_path: Path,
) -> None:
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE observations(match_id INT, player_slot INT, hero_id INT, partition VARCHAR, current_items INT[])"
    )
    con.execute(
        "INSERT INTO observations VALUES (1,1,12,'discovery',[2,3,5,6]),(2,1,12,'validation',[2,3,5,6]),(3,1,12,'test',[2,3,5,6]),(4,1,12,'discovery',[2])"
    )
    con.execute(
        "COPY observations TO ? (FORMAT PARQUET)",
        [str(tmp_path / "observations.parquet")],
    )
    con.execute(
        "CREATE TABLE purchases(match_id INT,player_slot INT,hero_id INT,item_id INT,buy_time INT,own_net_worth_at_buy INT,state_observed_at_s INT,event_order INT,duration_s INT)"
    )
    con.execute(
        "INSERT INTO purchases VALUES (1,1,12,7,1300,12000,1299,1,2000),(1,1,12,7,1400,14000,1399,2,2000),(2,1,12,8,100,2000,99,1,2000),(3,1,12,9,100,2000,99,1,2000),(4,1,12,10,100,2000,99,1,2000)"
    )
    result = collect(con, tmp_path, row_fixture())
    con.close()
    assert result["population"] == 1
    assert set(result["items"]) == {7}
    assert result["items"][7]["time_seconds_q25_q50_q75"] == [1300, 1300, 1300]


def test_readable_output_contains_entire_pool_decisions_and_candidate_status() -> None:
    guide, _ = guide_fixture()
    document = markdown(guide, details=True)
    assert "Candidate for review" in document
    assert "## Item pool" in document
    assert "OPTIONAL" in document
    assert "UPGRADE" in document
    assert "UPGRADE CORE" in document
    assert "Shared component cost" in document
    assert all(f"### {card['name']} —" in document for card in guide["choices"])
    guide["hero"] = "</script><img src=x onerror=alert(1)>"
    page = html([guide], guide["hero"])
    assert "</script><img" not in page
    assert "\\u003c/script" in page


def test_mechanic_units_are_not_duplicated() -> None:
    asset = {
        "properties": {
            "Speed": {"value": "1m", "postfix": "m", "label": "Sprint Speed"}
        },
        "tooltip_sections": [{"section_attributes": [{"properties": ["Speed"]}]}],
    }
    assert mechanics(asset) == "1m Sprint Speed"


def test_replan_refuses_modified_guide(tmp_path: Path) -> None:
    path = tmp_path / "guide.json"
    path.write_text("{}", encoding="utf-8")
    (tmp_path / "manifest.json").write_text(
        json.dumps({"files": {"guide.json": fingerprint(path)}}), encoding="utf-8"
    )
    path.write_text('{"tampered": true}', encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        replan(path, tmp_path / "state.json")
