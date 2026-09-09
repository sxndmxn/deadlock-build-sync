from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING

import duckdb
import polars as pl
import pytest

from deadlock_build_sync.offline import discovery_artifacts as artifacts
from deadlock_build_sync.offline import discovery_export as producer
from deadlock_build_sync.offline.config import RunPaths
from deadlock_build_sync.offline.discovery_admission import (
    admit_core,
    build_discovery_record,
)
from deadlock_build_sync.offline.discovery_quality import evaluate_core
from deadlock_build_sync.value_validation import (
    integer,
    require_object_dict,
    require_object_rows,
)
from tests.offline.discovery_fixtures import (
    make_frozen_guide,
    make_hero_discovery_data,
    make_item_graph,
    make_supported_mechanic_evidence,
)
from tests.offline.production_evidence_fixtures import (
    make_export_context,
    write_discovery_source_files,
)

if TYPE_CHECKING:
    from pathlib import Path

    from deadlock_build_sync.offline.discovery_data import HeroDiscoveryData
    from deadlock_build_sync.offline.discovery_types import (
        NominatedCoreBuild,
    )


@pytest.mark.parametrize("losing_validation", [False, True])
@pytest.mark.parametrize("hero_count", [1, 8])
def test_roster_freezes_all_identities_before_validation_and_reports_exclusions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hero_count: int,
    *,
    losing_validation: bool,
) -> None:
    paths = RunPaths.create(tmp_path, "frozen")
    duckdb.connect(str(paths.raw / "analysis.duckdb")).close()
    write_discovery_source_files(paths)
    context = replace(make_export_context(paths), item_graph=make_item_graph(13))
    values = make_hero_discovery_data()
    if losing_validation:
        values.won[values.fold_mask("validation")] = False
    monkeypatch.setattr(
        producer, "prepare_discovery_partitions", lambda _connection: None
    )
    monkeypatch.setattr(
        producer,
        "load_hero_discovery_data",
        lambda _cursor, hero, *_args: replace(values, hero=hero),
    )
    monkeypatch.setattr(producer, "load_checkpoint_rows", lambda *_args: [])
    monkeypatch.setattr(producer, "freeze_purchase_guide", make_frozen_guide)
    monkeypatch.setattr(
        producer, "describe_mechanic_overlap", make_supported_mechanic_evidence
    )
    original = producer.admit_core

    def checked(
        data: HeroDiscoveryData, row: NominatedCoreBuild, family: int, digest: str
    ) -> NominatedCoreBuild:
        frozen = list(paths.run.glob("discovery-nominations-*.json"))
        assert len(frozen) == 1
        document = require_object_dict(json.loads(frozen[0].read_text()))
        rows = require_object_rows(require_object_dict(document["6"])["rows"])
        assert len(document) == hero_count
        assert family == len(rows) * hero_count == 6 * hero_count
        assert all("validation" not in candidate for candidate in rows)
        return original(data, row, family, digest)

    monkeypatch.setattr(producer, "admit_core", checked)
    monkeypatch.setattr(
        producer,
        "build_evidence_payload",
        lambda _connection, _values, row, _assets: {
            "path_id": row["identity_id"],
            "rank": row["selection_rank"],
            "evidence_status": row["evidence_status"],
        },
    )
    heroes: list[dict[str, object]] = [
        {"id": hero, "name": f"Test Hero {hero}"} for hero in range(6, 6 + hero_count)
    ]
    results = producer.discover_hero_roster(heroes, context, workers=1)
    assert [result["hero_id"] for result in results] == [hero["id"] for hero in heroes]
    result = results[0]
    builds = require_object_rows(result["builds"])
    assert len(builds) == 6
    assert len({row["path_id"] for row in builds}) == 6
    assert [row["rank"] for row in builds] == sorted(
        integer(row["rank"]) for row in builds
    )
    assert result["exclusion"] is None
    if losing_validation:
        assert all(row["evidence_status"] == "observed" for row in builds)


def test_admission_cannot_bypass_order_mechanics_or_pool_failures() -> None:
    values = make_hero_discovery_data()
    row: NominatedCoreBuild = {
        "items": [0, 1, 2, 3],
        "selection": evaluate_core(values, (0, 1, 2, 3), "selection"),
        "selection_rejections": [],
        "path": {"order": [0, 1, 2, 3], "admitted_before_validation": False},
        "tactics": {
            **make_supported_mechanic_evidence(),
            "supported_focus": False,
            "reason": "Unsupported mechanics",
        },
        "guide": {"ready": False, "reason": "Empty pool"},
    }
    result = admit_core(values, row, 10, "frozen")
    assert len(result["rejections"]) == 2
    assert "Unsupported mechanics" in result["evidence_limitations"]
    record = build_discovery_record(result)
    assert record["test_evaluated"] is False
    assert "automatic_choices" not in record


def test_materialized_build_uses_frozen_pool_path_and_no_test_cohort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = make_hero_discovery_data()
    values.actors = tuple((int(match), 0) for match in values.matches)
    row: NominatedCoreBuild = {
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
        artifacts,
        "_query_path_item_metrics",
        lambda *_args: pl.DataFrame({"item_id": [0, 1, 2, 3, 4]}),
    )
    monkeypatch.setattr(
        artifacts, "_query_path_cohort_summary", lambda *_args: (800, 15000)
    )
    monkeypatch.setattr(
        artifacts,
        "_build_item_evidence_payload",
        lambda metric, _assets, _folds: metric,
    )
    connection = duckdb.connect()
    payload = artifacts.build_evidence_payload(connection, values, row, {})
    assert require_object_dict(payload["fold_eligible_player_matches"])["test"] == 0
    assert require_object_dict(payload["tier_policy"])["source_fold"] == "discovery"
    assert require_object_dict(payload["core_policy"])["default_item_ids"] == [
        0,
        1,
        2,
        3,
    ]
    monkeypatch.setattr(
        artifacts,
        "_query_path_item_metrics",
        lambda *_args: pl.DataFrame({"item_id": [0]}),
    )
    with pytest.raises(ValueError, match="incomplete purchase evidence"):
        artifacts.build_evidence_payload(connection, values, row, {})
    connection.close()
