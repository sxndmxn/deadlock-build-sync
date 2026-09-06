from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING

import duckdb
import polars as pl
import pytest

from deadlock_build_sync.offline import discovery_export as producer
from deadlock_build_sync.offline import discovery_materialize as materialize
from deadlock_build_sync.offline.config import RunPaths
from deadlock_build_sync.offline.discovery_admission import admit_core, discovery_record
from deadlock_build_sync.value_validation import (
    integer,
    require_object_dict,
    require_object_rows,
)
from tests.offline.test_discovery_identities import graph_fixture, planted_data
from tests.offline.test_production_orchestration import _context

if TYPE_CHECKING:
    from pathlib import Path

    from deadlock_build_sync.mechanics import ItemGraph
    from deadlock_build_sync.offline.discovery_data import HeroData
    from deadlock_build_sync.offline.discovery_types import (
        FrozenGuide,
        Nomination,
        Tactics,
    )


def frozen_guide(
    _con: duckdb.DuckDBPyConnection, _data: HeroData, row: Nomination, _graph: ItemGraph
) -> FrozenGuide:
    return {
        "ready": True,
        "path": row["path"]["order"],
        "pool": {"1": [], "2": [], "3": [], "4": []},
        "bounds": {},
        "purchase_timing": {"items": []},
        "pool_statistics": {},
    }


def supported_tactics(*_args: object) -> Tactics:
    return {
        "supported_focus": True,
        "focuses": [],
        "item_evidence": {},
        "reason": None,
        "limitation": "observational",
    }


@pytest.mark.parametrize("losing_validation", [False, True])
def test_roster_freezes_selection_before_validation_and_reports_exclusions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, losing_validation: bool
) -> None:
    paths = RunPaths.create(tmp_path, "frozen")
    duckdb.connect(str(paths.raw / "analysis.duckdb")).close()
    context = replace(_context(paths), item_graph=graph_fixture(13))
    values = planted_data()
    if losing_validation:
        values.won[values.mask("validation")] = False
    monkeypatch.setattr(producer, "prepare_partitions", lambda _con: None)
    monkeypatch.setattr(producer, "load_data", lambda *_args: values)
    monkeypatch.setattr(producer, "checkpoint_rows", lambda *_args: [])
    monkeypatch.setattr(producer, "freeze_guide", frozen_guide)
    monkeypatch.setattr(producer, "explain", supported_tactics)
    original = producer.admit_core

    def checked(
        data: HeroData, row: Nomination, family: int, digest: str
    ) -> Nomination:
        frozen = list(paths.run.glob("discovery-nominations-*.json"))
        assert len(frozen) == 1
        document = require_object_dict(json.loads(frozen[0].read_text()))
        assert (
            "validation"
            not in require_object_rows(require_object_dict(document["6"])["rows"])[0]
        )
        return original(data, row, family, digest)

    monkeypatch.setattr(producer, "admit_core", checked)
    monkeypatch.setattr(
        producer,
        "build_payload",
        lambda _con, _values, row, _assets: {
            "path_id": row["identity_id"],
            "rank": row["selection_rank"],
        },
    )
    result = producer.discover_roster([{"id": 6, "name": "Test Hero"}], context)[0]
    if losing_validation:
        assert result["builds"] == []
        assert require_object_dict(result["exclusion"])["candidate_rejections"]
    else:
        builds = require_object_rows(result["builds"])
        assert 1 <= len(builds) <= 3
        assert [row["rank"] for row in builds] == sorted(
            integer(row["rank"]) for row in builds
        )
        assert result["exclusion"] is None


def test_admission_cannot_bypass_order_mechanics_or_pool_failures() -> None:
    values = planted_data()
    row: Nomination = {
        "items": [0, 1, 2, 3],
        "path": {"order": [0, 1, 2, 3], "admitted_before_validation": False},
        "tactics": {
            **supported_tactics(),
            "supported_focus": False,
            "reason": "Unsupported mechanics",
        },
        "guide": {"ready": False, "reason": "Empty pool"},
    }
    result = admit_core(values, row, 10, "frozen")
    assert len(result["rejections"]) == 3
    record = discovery_record(result)
    assert record["test_evaluated"] is False
    assert "automatic_choices" not in record


def test_materialized_build_uses_frozen_pool_path_and_no_test_cohort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = planted_data()
    values.actors = tuple((int(match), 0) for match in values.matches)
    row: Nomination = {
        "items": [0, 1, 2, 3],
        "path": {"order": [0, 1, 2, 3]},
        "identity_id": "core",
        "names": ["A", "B", "C", "D"],
        "validation": {},
        "order_validation": {
            "owners": 100,
            "ordered_owners": 100,
            "share": 1,
            "passes": True,
        },
        "guide": {
            "path": [0, 1, 2, 3],
            "pool": {"1": [4], "2": [], "3": [], "4": []},
            "pool_statistics": {},
            "purchase_timing": {},
        },
        "automatic_choices": {"version": 1, "branches": []},
    }
    monkeypatch.setattr(
        materialize,
        "_path_item_metrics",
        lambda *_args: pl.DataFrame({"item_id": [0, 1, 2, 3, 4]}),
    )
    monkeypatch.setattr(
        materialize, "_path_cohort_summary", lambda *_args: (800, 15000)
    )
    monkeypatch.setattr(
        materialize, "_item_payload", lambda metric, _assets, _folds: metric
    )
    con = duckdb.connect()
    payload = materialize.build_payload(con, values, row, {})
    assert require_object_dict(payload["fold_eligible_player_matches"])["test"] == 0
    assert require_object_dict(payload["tier_policy"])["source_fold"] == "discovery"
    assert require_object_dict(payload["core_policy"])["default_item_ids"] == [
        0,
        1,
        2,
        3,
    ]
    monkeypatch.setattr(
        materialize, "_path_item_metrics", lambda *_args: pl.DataFrame({"item_id": [0]})
    )
    with pytest.raises(ValueError, match="incomplete purchase evidence"):
        materialize.build_payload(con, values, row, {})
    con.close()
