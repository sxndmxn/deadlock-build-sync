"""Check freeze order, unchanged groups, and explicit generator fallbacks."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING

import duckdb
import pytest

from deadlock_build_sync.offline import beam_export as exporter
from deadlock_build_sync.offline import beam_nomination as nominator
from deadlock_build_sync.offline.beam_export import assemble_group, generate_beam_roster
from deadlock_build_sync.offline.beam_nomination import core_items
from deadlock_build_sync.offline.beam_snapshot import (
    beam_resume_record,
    require_beam_resume,
)
from deadlock_build_sync.offline.config import RunPaths
from deadlock_build_sync.offline.discovery_admission import build_discovery_record
from deadlock_build_sync.value_validation import (
    require_object_dict,
    require_object_rows,
)
from tests.offline.discovery_fixtures import (
    make_frozen_guide,
    make_item_graph,
    make_supported_mechanic_evidence,
)
from tests.offline.production_evidence_fixtures import (
    make_export_context,
    write_discovery_source_files,
)
from tests.offline.test_beam_search import make_beam_model, make_beam_values

if TYPE_CHECKING:
    from pathlib import Path

    from deadlock_build_sync.mechanics import ItemGraph
    from deadlock_build_sync.offline.discovery_data import HeroDiscoveryData
    from deadlock_build_sync.offline.discovery_types import (
        FrozenPurchaseGuide,
        NominatedCoreBuild,
    )


def make_baseline() -> dict[str, object]:
    return {
        "hero_id": 6,
        "hero": "Test Hero",
        "cohort": {"minimum_badge": 71, "maximum_badge": 115},
        "builds": [
            {
                "path_id": group,
                "guide_group_id": group,
                "core_policy": {"default_item_ids": list(range(start, start + 4))},
                "discovery": {"hero_id": 6, "selection_rank": index},
            }
            for index, (group, start) in enumerate((("first", 0), ("second", 4)))
        ],
    }


@pytest.mark.parametrize("mode", ["accept", "reject", "incomplete", "order"])
def test_all_nominations_precede_validation_and_groups_survive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    paths = RunPaths.create(tmp_path, "beam")
    duckdb.connect(str(paths.raw / "analysis.duckdb")).close()
    write_discovery_source_files(paths)
    graph, values = make_item_graph(13), make_beam_values()
    context = replace(make_export_context(paths), item_graph=graph)
    for module in (exporter, nominator):
        monkeypatch.setattr(module, "prepare_discovery_partitions", lambda _c: None)
        monkeypatch.setattr(module, "load_hero_discovery_data", lambda *_args: values)
    monkeypatch.setattr(
        nominator, "load_beam_model", lambda *_args: make_beam_model(graph)
    )
    monkeypatch.setattr(
        nominator, "describe_mechanic_overlap", make_supported_mechanic_evidence
    )

    def freeze(
        connection: duckdb.DuckDBPyConnection,
        data: HeroDiscoveryData,
        row: NominatedCoreBuild,
        graph: ItemGraph,
        *,
        exact_path: tuple[int, ...],
    ) -> FrozenPurchaseGuide:
        assert exact_path
        return {
            **make_frozen_guide(connection, data, row, graph),
            "path": list(exact_path),
        }

    monkeypatch.setattr(nominator, "freeze_purchase_guide", freeze)
    original = exporter.admit_core

    def admit(
        data: HeroDiscoveryData, row: NominatedCoreBuild, family: int, digest: str
    ) -> NominatedCoreBuild:
        snapshots = list(paths.run.glob("*nominations-*.json"))
        assert len(snapshots) == 1
        snapshot = require_object_dict(json.loads(snapshots[0].read_text()))
        assert snapshot["implementation"]
        proposals = require_object_rows(
            require_object_dict(require_object_dict(snapshot["heroes"])["6"])[
                "proposals"
            ]
        )
        assert proposals and all(
            "validation" not in require_object_dict(proposal["row"])
            for proposal in proposals
        )
        result = original(data, row, family, digest)
        if mode == "reject":
            result["rejections"] = ["Unsupported test order"]
        return result

    monkeypatch.setattr(exporter, "admit_core", admit)
    monkeypatch.setattr(
        exporter,
        "build_evidence_payload",
        lambda _c, _v, row, _a: {
            "path_id": row["identity_id"],
            "core_policy": {"default_item_ids": row["items"]},
            "discovery": build_discovery_record(row),
        },
    )
    monkeypatch.setattr(
        exporter,
        "complete_guide_rejection",
        lambda *_args: "Missing item coverage" if mode == "incomplete" else None,
    )
    baseline = make_baseline()
    result = generate_beam_roster(
        [{"id": 6, "name": "Test Hero"}],
        [baseline],
        context,
        workers=1,
        order_only=mode == "order",
    )
    builds = require_object_rows(result[0]["builds"])
    assert list(dict.fromkeys(build["guide_group_id"] for build in builds)) == [
        "first",
        "second",
    ]
    defaults = [
        build for build in builds if build["path_id"] == build["guide_group_id"]
    ]
    assert len(defaults) == 2
    expected = "current" if mode in {"reject", "incomplete"} else "beam"
    assert all(
        require_object_dict(build["generator"])["effective"] == expected
        for build in defaults
    )
    assert baseline == make_baseline()
    if mode == "order":
        assert [core_items(build) for build in builds] == [
            core_items(build) for build in require_object_rows(baseline["builds"])
        ]


def test_order_control_keeps_default_even_when_another_core_scores_higher() -> None:
    baseline = require_object_rows(make_baseline()["builds"])
    variants = [
        {**build, "generator": {"states": [1], "effective": "beam"}}
        for build in reversed(baseline)
    ]
    result = assemble_group(baseline, variants, "first", order_only=True)
    assert [core_items(build) for build in result] == [
        core_items(build) for build in baseline
    ]
    assert result[0] is variants[1]


def test_beam_resume_rejects_changed_settings_or_code() -> None:
    record = beam_resume_record()
    require_beam_resume({"beam_resume": record})
    require_object_dict(record["generator"])["version"] = "changed"
    with pytest.raises(ValueError, match="settings or code differ"):
        require_beam_resume({"beam_resume": record})
    with pytest.raises(ValueError, match="settings or code differ"):
        require_beam_resume({})
