from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from deadlock_build_sync.offline import (
    production_evidence as current_production_evidence,
)
from deadlock_build_sync.offline.api import write_json
from deadlock_build_sync.offline.config import RunPaths, sha256_json
from tests.mechanics_fixtures import make_item_asset

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def _return(value: object) -> Callable[..., object]:
    def result(*_args: object, **_kwargs: object) -> object:
        return value

    return result


def test_export_production_evidence_writes_closed_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = RunPaths.create(tmp_path, "export")
    asset = {
        **make_item_asset(1, "item_1"),
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
    monkeypatch.setattr(
        current_production_evidence,
        "_select_patch_at_timestamp",
        _return({"identity": "patch", "start_timestamp": 1}),
    )
    monkeypatch.setattr(
        current_production_evidence,
        "discover_hero_roster",
        _return([{"hero_id": 7, "hero": "Hero", "builds": [{"path_id": "test"}]}]),
    )
    target = paths.run / "build-evidence.json"

    monkeypatch.setattr(
        current_production_evidence,
        "write_validated_evidence",
        lambda path, value: path.write_text(json.dumps(value)),
    )
    document = current_production_evidence.export_production_evidence(paths, target)

    assert target.exists()
    assert document["requested_hero_ids"] == [7]
    assert len(str(document["artifact_id"])) == 64
    assert sha256_json(document) == (
        "f0bbf318ef4846b248a9cad9b69782baa7e77573fdb82a8eaa75fb82f5a2c0be"
    )
    previous = target.read_bytes()
    monkeypatch.setattr(
        current_production_evidence,
        "discover_hero_roster",
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
