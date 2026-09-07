from __future__ import annotations

import json
from collections import Counter
from typing import TYPE_CHECKING, cast

import duckdb
import polars as pl
import pytest

from deadlock_build_sync.mechanics import ItemGraph
from deadlock_build_sync.offline import (
    production_evidence as current_production_evidence,
)
from deadlock_build_sync.offline.api import write_json
from deadlock_build_sync.offline.config import RunPaths, sha256_json
from deadlock_build_sync.offline.production_sources import (
    UnsupportedBuildPathError,
    _HeroExportContext,
)
from deadlock_build_sync.value_validation import object_dict, object_list
from tests.mechanics_fixtures import item
from tools.comparisons.legacy import production_evidence, production_paths
from tools.comparisons.legacy.build_paths import DiscoveredBuildPath
from tools.comparisons.legacy.core_policy import BackboneSelection

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


class _FakeDatabase:
    def __init__(self) -> None:
        self.closed = False
        self.queries: list[str] = []

    def execute(self, query: str) -> _FakeDatabase:
        self.queries.append(query)
        return self

    def close(self) -> None:
        self.closed = True


def _return(value: object) -> Callable[..., object]:
    def result(*_args: object, **_kwargs: object) -> object:
        return value

    return result


def _graph() -> ItemGraph:
    return ItemGraph.from_assets([
        {
            **item(item_id, f"item_{item_id}"),
            "cost": item_id * 500,
            "item_tier": item_id,
        }
        for item_id in (1, 2, 3, 4)
    ])


def _context(paths: RunPaths) -> _HeroExportContext:
    graph = _graph()
    assets = {item_id: item(item_id, f"item_{item_id}") for item_id in graph.nodes}
    return _HeroExportContext(
        paths=paths,
        hero_count=1,
        components={},
        folds_by_match={1: "train", 2: "validation", 3: "test"},
        normal_assets=list(assets.values()),
        item_graph=graph,
        mechanics_assets_by_id=assets,
        item_costs={item_id: item_id * 500 for item_id in graph.nodes},
        target_core_cost=3_000,
        enemy_threat_evidence={},
    )


def _path() -> DiscoveredBuildPath:
    return DiscoveredBuildPath(
        "path",
        frozenset({(1, 0), (2, 0), (3, 0)}),
        (1,),
        {"train": 1, "validation": 1, "test": 1},
        {"method": "test"},
    )


def _patch_path_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    metrics = pl.DataFrame({"item_id": [1, 2, 3]})
    backbone = BackboneSelection(
        (1,),
        3,
        {"train": 1, "validation": 1, "test": 1},
        ({"stage": "backbone"},),
    )
    monkeypatch.setattr(production_paths, "_path_item_metrics", _return(metrics))
    monkeypatch.setattr(production_paths, "_path_cohort_summary", _return((3, 4_000)))
    monkeypatch.setattr(production_paths, "_purchase_priorities", _return({}))
    monkeypatch.setattr(production_paths, "_complete_priorities", _return({}))
    monkeypatch.setattr(production_paths, "_purchase_window_bounds", _return({}))
    monkeypatch.setattr(
        production_paths, "select_supported_backbone", _return(backbone)
    )
    monkeypatch.setattr(
        production_paths,
        "complete_default_core",
        _return((
            (1, 2),
            2,
            [
                {
                    "selected": True,
                    "joint_fold_matches": {"train": 1, "validation": 1},
                }
            ],
        )),
    )
    monkeypatch.setattr(
        production_paths, "_core_target_order", _return(((1, 2), {"route": "ok"}))
    )
    monkeypatch.setattr(
        production_paths,
        "_core_alternatives",
        _return(([{"item_id": 3}], [{"stage": "alternative"}])),
    )
    monkeypatch.setattr(production_paths, "_expanded_default_path", _return([1, 2]))
    monkeypatch.setattr(
        production_paths,
        "_tier_policy",
        _return({"item_ids_by_tier": {"1": [1, 3]}}),
    )
    monkeypatch.setattr(production_paths, "_situational_policy", _return({"items": []}))
    monkeypatch.setattr(production_paths, "_sequence_rows", _return([{"item": 1}]))
    monkeypatch.setattr(production_paths, "timing_payload", _return({"version": 1}))
    monkeypatch.setattr(
        production_paths, "_sequence_evaluation", _return({"top1": 0.5})
    )
    monkeypatch.setattr(
        production_paths,
        "_item_payload",
        _return({"item_id": 1, "name": "Item"}),
    )


def test_build_path_payload_composes_supported_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_path_dependencies(monkeypatch)
    context = _context(RunPaths.create(tmp_path, "path"))
    inventories: dict[tuple[int, int], tuple[int, ...]] = {
        (1, 0): (1, 2),
        (2, 0): (1, 2),
        (3, 0): (1, 2),
    }

    payload = production_paths._build_path_payload(
        duckdb.connect(),
        7,
        {"id": 7},
        _path(),
        "Core",
        Counter({"Core": 2}),
        inventories,
        context,
        core_decisions=pl.DataFrame(),
        situational_evidence=(pl.DataFrame(), pl.DataFrame()),
    )

    assert payload["path_id"] == "path"
    assert payload["path_label"] == "Core / item_1"
    assert payload["selection_eligible_player_matches"] == 2
    core = object_dict(payload["core_policy"])
    assert core is not None
    assert core["default_item_ids"] == [1, 2]
    candidate_audit = object_list(core["candidate_audit"])
    assert candidate_audit is not None
    assert len(candidate_audit) == 3
    sequence = object_dict(payload["sequence_policy"])
    assert sequence is not None
    assert sequence["component_expanded_default_path"] == [1, 2]


def test_path_helpers_cover_labels_members_fallback_and_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _path()
    assert (
        production_paths._resolved_path_label("Core", path, Counter({"Core": 1}), {})
        == "Core"
    )
    assert (
        production_paths._resolved_path_label(
            "Core", path, Counter({"Core": 2}), {1: {"name": " "}}
        )
        == "Core"
    )
    assert production_paths._supported_route_members(
        {(1, 0): (1, 2), (2, 0): (1,), (3, 0): (1, 2)},
        (1, 2),
        {1: "train", 2: "train", 3: "test"},
    ) == {(1, 0)}
    contract = production_paths._core_evaluation_contract()
    assert contract["support_floor"] == 20
    fallback = production_paths._fallback_build_path(
        {(1, 0): (1,), (2, 0): (2,)},
        {1: "train", 2: "test"},
    )
    assert fallback.fold_support == {"train": 1, "test": 1}

    _patch_path_dependencies(monkeypatch)
    monkeypatch.setattr(
        production_paths,
        "select_supported_backbone",
        _raise_backbone,
    )
    with pytest.raises(UnsupportedBuildPathError, match="no backbone"):
        production_paths._build_path_payload(
            duckdb.connect(),
            7,
            {"id": 7},
            path,
            "Core",
            Counter({"Core": 1}),
            {(1, 0): (1,), (2, 0): (1,), (3, 0): (1,)},
            _context(RunPaths.create(tmp_path, "error")),
        )


def _raise_backbone(*_args: object, **_kwargs: object) -> BackboneSelection:
    raise RuntimeError("no backbone")


def test_build_hero_payload_opens_queries_and_closes_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeDatabase()

    def connect(*_args: object, **_kwargs: object) -> duckdb.DuckDBPyConnection:
        return cast("duckdb.DuckDBPyConnection", fake)

    context = _context(RunPaths.create(tmp_path, "hero"))
    monkeypatch.setattr(production_evidence.duckdb, "connect", connect)
    monkeypatch.setattr(
        production_evidence,
        "_inventories_for_hero",
        _return({(1, 0): (1, 2)}),
    )
    monkeypatch.setattr(
        production_evidence,
        "_early_inventories_for_hero",
        _return({(1, 0): (1,)}),
    )
    monkeypatch.setattr(
        production_evidence, "discover_build_paths", _return((_path(),))
    )
    monkeypatch.setattr(production_evidence, "_core_decisions", _return(pl.DataFrame()))
    monkeypatch.setattr(
        production_evidence, "_situational_state_overlap", _return(pl.DataFrame())
    )
    monkeypatch.setattr(
        production_evidence, "_situational_cells", _return(pl.DataFrame())
    )
    monkeypatch.setattr(
        production_evidence,
        "_path_payloads",
        _return(([{"path_id": "path"}], [])),
    )

    result = production_evidence._build_hero_payload(
        (1, {"id": 7, "name": "Hero"}),
        context=context,
    )

    assert result == {
        "hero_id": 7,
        "hero": "Hero",
        "builds": [{"path_id": "path"}],
        "path_abstentions": [],
    }
    assert fake.closed
    assert fake.queries == ["SET threads = 1"]


def test_export_production_evidence_writes_closed_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = RunPaths.create(tmp_path, "export")
    asset = {
        **item(1, "item_1"),
        "cost": 500,
        "item_tier": 1,
        "game_mode": "normal",
    }
    hero = {"id": 7, "name": "Hero"}
    write_json(
        paths.run / "manifest.json",
        {
            "cohort": {
                "as_of": "2026-08-30T00:00:00+00:00",
                "minimum_badge": 71,
                "maximum_badge": 115,
            },
            "sources": {"client_version": 123, "source_sha256": {}},
            "frozen_data_sha256": {},
        },
    )
    write_json(paths.raw / "heroes.json", [hero])
    write_json(paths.raw / "items.json", [asset])
    write_json(paths.raw / "items-all.json", [asset])
    write_json(paths.raw / "ranks.json", [])
    fake = _FakeDatabase()

    def connect(*_args: object, **_kwargs: object) -> duckdb.DuckDBPyConnection:
        return cast("duckdb.DuckDBPyConnection", fake)

    monkeypatch.setattr(current_production_evidence.duckdb, "connect", connect)
    monkeypatch.setattr(
        current_production_evidence, "_folds_by_match", _return({1: "train"})
    )
    monkeypatch.setattr(
        current_production_evidence,
        "_patch_at",
        _return({"identity": "patch", "start_timestamp": 1}),
    )
    monkeypatch.setattr(
        current_production_evidence,
        "_enemy_threat_evidence",
        _return({}),
    )
    monkeypatch.setattr(
        current_production_evidence,
        "discover_roster",
        _return([{"hero_id": 7, "hero": "Hero", "builds": [{"path_id": "test"}]}]),
    )
    target = paths.run / "build-evidence.json"

    monkeypatch.setattr(
        current_production_evidence,
        "validated_write",
        lambda path, value: path.write_text(json.dumps(value)),
    )
    document = current_production_evidence.export_production_evidence(paths, target)

    assert target.exists()
    assert document["requested_hero_ids"] == [7]
    assert len(str(document["artifact_id"])) == 64
    assert sha256_json(document) == (
        "f0bbf318ef4846b248a9cad9b69782baa7e77573fdb82a8eaa75fb82f5a2c0be"
    )
    assert fake.closed
    previous = target.read_bytes()
    monkeypatch.setattr(
        current_production_evidence,
        "discover_roster",
        _return([
            {
                "hero_id": 7,
                "hero": "Hero",
                "builds": [],
                "exclusion": {"reason": "weak outcome"},
            }
        ]),
    )
    with pytest.raises(ValueError, match=r"Requested heroes lack.*unchanged"):
        current_production_evidence.export_production_evidence(paths, target)
    assert target.read_bytes() == previous
    assert "weak outcome" in (paths.run / "discovery-exclusions.json").read_text()


def test_export_rejects_invalid_manifest(tmp_path: Path) -> None:
    paths = RunPaths.create(tmp_path, "bad-export")
    write_json(paths.run / "manifest.json", [])
    with pytest.raises(RuntimeError, match="must be a dictionary"):
        current_production_evidence.export_production_evidence(
            paths, paths.run / "output.json"
        )

    write_json(paths.run / "manifest.json", {})
    with pytest.raises(RuntimeError, match="lacks frozen cohort"):
        current_production_evidence.export_production_evidence(
            paths, paths.run / "output.json"
        )
