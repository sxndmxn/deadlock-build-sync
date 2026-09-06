"""Read-only CLI rendering, legacy guide recovery, and artifact integrity."""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING

import pytest

from experiments.build_guides.run import main, replan
from experiments.build_guides.schema import load_guide
from experiments.build_guides.test_build_guides import guide_fixture
from experiments.qdfm.extract import fingerprint

if TYPE_CHECKING:
    from pathlib import Path


def write_fixture(directory: Path, version: int = 2) -> tuple:
    guide, graph = guide_fixture()
    guide["schema_version"] = version
    assets = [
        {
            "id": item,
            "class_name": f"item_{item}",
            "name": node.name,
            "cost": node.cost,
            "component_items": [f"item_{part}" for part in graph.components[item]],
            "item_slot_type": "spirit",
            "item_tier": node.tier,
            "shopable": True,
            "disabled": False,
            "is_active_item": node.active,
        }
        for item, node in graph.nodes.items()
    ]
    source = directory / "items.json"
    source.write_text(json.dumps(assets), encoding="utf-8")
    guide["catalog_source"] = {"path": str(source), "sha256": fingerprint(source)}
    path = directory / "guide.json"
    path.write_text(json.dumps(guide), encoding="utf-8")
    manifest = directory / "manifest.json"
    manifest.write_text(
        json.dumps({"files": {path.name: fingerprint(path)}}), encoding="utf-8"
    )
    return path, source, manifest


def test_show_prints_phone_markdown_and_details_without_changing_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path, _, _ = write_fixture(tmp_path, version=1)
    before = {row.name: row.read_bytes() for row in tmp_path.iterdir()}
    monkeypatch.setattr(
        sys, "argv", ["guides", "show", "--guide", str(path), "--format", "markdown"]
    )
    main()
    concise = capsys.readouterr().out
    assert concise.startswith("# Kelvin")
    assert "## Item pool" in concise
    assert "Path with this choice" not in concise
    monkeypatch.setattr(
        sys, "argv", ["guides", "show", "--guide", str(path), "--details"]
    )
    main()
    assert "Path with this choice" in capsys.readouterr().out
    assert {row.name: row.read_bytes() for row in tmp_path.iterdir()} == before


def test_loader_verifies_catalog_before_legacy_adaptation(tmp_path: Path) -> None:
    path, source, _ = write_fixture(tmp_path, version=1)
    source.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="catalog changed"):
        load_guide(path)


@pytest.mark.parametrize("version", [3, True, "2"])
def test_loader_rejects_unknown_schema(tmp_path: Path, version: int) -> None:
    path, _, _ = write_fixture(tmp_path, version=version)
    with pytest.raises(ValueError, match="schema version"):
        load_guide(path)


def test_replan_accepts_override_and_rejects_unrecognized_state(tmp_path: Path) -> None:
    path, _, _ = write_fixture(tmp_path)
    state = tmp_path / "state.json"
    state.write_text(
        json.dumps({
            "selected_items": [9],
            "placement_overrides": {"9": 0},
            "liquid_souls": 500,
        }),
        encoding="utf-8",
    )
    result = replan(path, state)
    assert result["next_action"]["item_id"] == 9
    assert result["decision"] == "save"
    assert result["save_souls"] == 1100
    assert not result["core_path_supported"]
    assert not result["full_policy_validated"]
    state.write_text('{"ahead": true}', encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported state fields"):
        replan(path, state)
