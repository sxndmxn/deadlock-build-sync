"""Supported build availability is independent of an estimated win advantage."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import TYPE_CHECKING

import duckdb
import numpy as np
import pytest

from deadlock_build_sync.build_evidence_discovery import validate_discovery
from deadlock_build_sync.offline import discovery_export as producer
from deadlock_build_sync.offline import discovery_materialize, discovery_orders
from deadlock_build_sync.offline.config import RunPaths
from deadlock_build_sync.offline.discovery_admission import admit_core, discovery_record
from deadlock_build_sync.offline.discovery_fit import select
from deadlock_build_sync.offline.discovery_pool import summarize
from deadlock_build_sync.offline.discovery_quality import evaluate_core
from deadlock_build_sync.value_validation import require_object_rows
from tests.offline.test_discovery_export import frozen_guide, supported_tactics
from tests.offline.test_discovery_identities import (
    catalog_fixture,
    graph_fixture,
    planted_data,
)
from tests.offline.test_production_orchestration import _context

if TYPE_CHECKING:
    from pathlib import Path

    from deadlock_build_sync.offline.discovery_data import HeroData
    from deadlock_build_sync.offline.discovery_types import Candidate, Nomination


def test_viscous_overlap_case_remains_available_with_negative_validation() -> None:
    values = planted_data(per_fold=1500)
    values.won[values.mask("validation")] = False
    selection = evaluate_core(values, (0, 1, 2, 3), "selection")
    selection["adjusted"].update({"core_overlap": 383, "overlap_share": 0.766})
    row: Nomination = {
        "items": [0, 1, 2, 3],
        "discovery_support": 500,
        "selection": selection,
        "selection_rejections": [],
        "selection_rank": 0,
        "path": discovery_orders.choose_order(
            values, [0, 1, 2, 3], "pairwise", graph_fixture()
        ),
        "tactics": supported_tactics(),
        "guide": {"ready": True, "path": [0, 1, 2, 3], "bounds": {}},
    }
    result = admit_core(values, row, 100, "frozen")
    assert result["rejections"] == []
    assert result["evidence_status"] == "observed"
    assert (
        "selection: insufficient comparable-state overlap"
        in result["evidence_limitations"]
    )
    assert result["validation"]["win_rate"] == 0
    validate_discovery(discovery_record(result), (0, 1, 2, 3), (0, 1, 2, 3))


def test_missing_optional_economy_disables_estimate_without_losing_owners() -> None:
    data = planted_data()
    data.wealth[:] = np.nan
    data.lead[:] = np.nan
    result = evaluate_core(data, (0, 1, 2, 3), "selection")
    assert result["owners"] == 400
    assert result["adjusted"]["difference"] is None
    assert result["adjusted"]["core_overlap"] == 0


def test_candidates_with_estimates_precede_missing_estimates_even_when_negative() -> (
    None
):
    candidates: list[Candidate] = [
        {
            "items": [item],
            "selection_rejections": [],
            "selection": {"owners": owners, "adjusted": {"lower_95": lower}},
        }
        for item, lower, owners in (
            (4, None, 600),
            (3, -0.1, 100),
            (2, 0.0, 100),
            (1, None, 600),
            (5, 0.0, 200),
        )
    ]
    assert select(candidates) == [4, 2, 1, 3, 0]


def test_pairwise_search_tries_the_next_legal_supported_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        discovery_orders,
        "ranked_orders",
        lambda *_args: [(100, [1, 0, 2, 3]), (90, [0, 1, 2, 3])],
    )
    order = discovery_orders.choose_order(
        planted_data(), [0, 1, 2, 3], "pairwise", graph_fixture()
    )
    assert order["order"] == [0, 1, 2, 3]
    assert order["admitted_before_validation"]
    assert order["ranking_score"] == 90


def test_empty_optional_tiers_and_conflicting_wealth_keep_legal_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = planted_data()
    data.actors = tuple((int(match), 0) for match in data.matches)
    evidence = summarize(
        [
            (match, 0, item, 100 + item * 10, 20000.0 - item * 4000, 99 + item * 10)
            for match in range(100)
            for item in range(4)
        ],
        100,
    )
    monkeypatch.setattr(discovery_materialize, "pool_evidence", lambda *_args: evidence)
    row: Nomination = {"items": [0, 1, 2, 3], "path": {"order": [0, 1, 2, 3]}}
    with duckdb.connect() as con:
        result = discovery_materialize.freeze_guide(con, data, row, graph_fixture())
    assert result["ready"]
    assert result["path"] == [0, 1, 2, 3]
    assert result["timing_status"] == "uncertain"
    assert result["pool"] == {"1": [], "2": [], "3": [], "4": []}


@pytest.mark.parametrize(
    ("mode", "supported_at", "expected"),
    [
        ("auto", 61, [71, 61]),
        ("off", 61, [71]),
        ("auto", 71, [71]),
        ("auto", 0, [71, 61, 51, 41, 31, 21, 11]),
    ],
)
def test_rank_expansion_stops_on_support_or_exhaustion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    supported_at: int,
    expected: list[int],
) -> None:
    context = replace(
        _context(RunPaths.create(tmp_path, "ranges")),
        item_graph=graph_fixture(13),
        rank_expansion=mode,
    )
    values = planted_data()
    empty = replace(
        values,
        matrix=np.zeros_like(values.matrix),
        times=np.full_like(values.times, -1),
    )
    attempted: list[int] = []

    def load(
        _con: object, _hero: int, _graph: object, minimum: int, maximum: int
    ) -> HeroData:
        assert maximum == 115
        attempted.append(minimum)
        return values if minimum <= supported_at else empty

    monkeypatch.setattr(producer, "load_data", load)
    monkeypatch.setattr(producer, "checkpoint_rows", lambda *_args: [])
    monkeypatch.setattr(producer, "freeze_guide", frozen_guide)
    monkeypatch.setattr(producer, "explain", supported_tactics)
    with duckdb.connect() as con:
        _, frozen = producer._freeze_hero(
            con, {"id": 6, "name": "Test"}, context, catalog_fixture(13)
        )
        if not frozen["rows"]:
            result = producer._validate_hero(
                con,
                {"id": 6, "name": "Test"},
                (empty, frozen),
                context,
                producer.ValidationFamily(1, 1, "frozen"),
            )
            assert "attempted rank ranges" in str(result["exclusion"])
    assert attempted == expected
    history = require_object_rows(frozen["cohort"]["expansion_history"])
    assert [row["minimum_badge"] for row in history] == expected
    assert bool(frozen["rows"]) == (supported_at >= expected[-1])
    assert all(row["supported_builds"] == 0 for row in history[:-1])


def test_three_item_seeds_and_candidates_after_the_first_three(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = replace(
        _context(RunPaths.create(tmp_path, "seeds")), item_graph=graph_fixture(13)
    )
    values = planted_data()
    monkeypatch.setattr(producer, "load_data", lambda *_args: values)
    monkeypatch.setattr(producer, "checkpoint_rows", lambda *_args: [])
    monkeypatch.setattr(producer, "freeze_guide", frozen_guide)
    monkeypatch.setattr(producer, "explain", supported_tactics)
    original = producer.choose_order
    calls: list[list[int]] = []

    def ordered(
        data: HeroData, items: list[int], method: str, _graph: object
    ) -> discovery_orders.Order:
        calls.append(items)
        order = original(data, items, method, context.item_graph)
        if len(calls) <= 3:
            order.update({"admitted_before_validation": False, "reason": "unsupported"})
        return order

    monkeypatch.setattr(producer, "choose_order", ordered)
    with duckdb.connect() as con:
        _, frozen = producer._freeze_hero(
            con, {"id": 6, "name": "Test"}, context, catalog_fixture(13)
        )
        assert frozen["rows"] and frozen["rows"][0]["selection_rank"] >= 3
        seed_data = deepcopy(values)
        seed_data.matrix[:, [3, 7, 11, 12]] = False
        seed_data.times[:, [3, 7, 11, 12]] = -1
        monkeypatch.setattr(producer, "load_data", lambda *_args: seed_data)
        _, seeds = producer._freeze_hero(
            con, {"id": 6, "name": "Test"}, context, catalog_fixture(13)
        )
    assert seeds["rows"]
    assert all(len(row["items"]) == 3 for row in seeds["rows"])
    assert len(require_object_rows(seeds["cohort"]["expansion_history"])) == 1
