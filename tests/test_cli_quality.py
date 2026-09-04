from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from deadlock_build_sync.ability_order import AbilityPath
from deadlock_build_sync.cli import main
from deadlock_build_sync.quality_inputs import (
    QualityInputs,
    load_quality_inputs,
    load_replay_assets,
)
from deadlock_build_sync.recommendation_state import RecommendationError
from deadlock_build_sync.snapshot import sha256_json
from tests.artifact_bundle_fixtures import _write_bundle
from tests.quality_fixtures import replay_document, replay_row
from tests.recommendation_fixtures import assets, build_policy, catalog

if TYPE_CHECKING:
    from pathlib import Path


def test_quality_cli_reports_missing_replay_without_steam_or_network(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_bundle(tmp_path)
    monkeypatch.setattr("deadlock_build_sync.cli._location", _unexpected_access)
    monkeypatch.setattr("deadlock_build_sync.api.DeadlockApi.items", _unexpected_access)
    result = main(["quality-report", "--artifacts", str(tmp_path)])
    captured = capsys.readouterr()
    assert result == 2, captured.err
    report = json.loads(captured.out)
    assert report["status"] == "unevaluated"
    assert report["builds"][0]["ability"]["status"] == "unevaluated"
    assert report["builds"][0]["replay"]["summary"]["decisions"] == 0
    assert report["builds"][0]["core_support_by_fold"]
    assert len(report["report_id"]) == 64


def _unexpected_access(_argument: object) -> None:
    raise AssertionError("quality report must not discover Steam or fetch analytics")


def test_quality_cli_requires_pinned_assets_for_replay(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_bundle(tmp_path)
    assert (
        main(["quality-report", "--artifacts", str(tmp_path), "--replay", "later.json"])
        == 1
    )
    assert "requires --assets" in capsys.readouterr().err


def test_quality_cli_replays_frozen_inputs_and_omits_group_identifiers(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = replace(catalog(), items_sha256=sha256_json(assets()))
    policy = build_policy()
    ability = AbilityPath(
        (1, 2, 3, 4) * 4,
        20,
        10,
        10,
        20,
        decision_support=(20,) * 16,
        filter_item_ids=(1, 2, 4, 5),
    )
    inputs = QualityInputs(
        evidence,
        (policy,),
        {policy.policy_id: ability},
        "d" * 64,
        evidence.as_of_timestamp,
    )

    def frozen_inputs(_directory: Path) -> QualityInputs:
        return inputs

    monkeypatch.setattr(
        "deadlock_build_sync.cli_quality.load_quality_inputs", frozen_inputs
    )
    row = replay_row()
    row.update(
        match_start_timestamp=inputs.cutoff + 100,
        policy_assigned_at=inputs.cutoff + 90,
        feature_as_of_timestamp=inputs.cutoff + 200,
    )
    replay = tmp_path / "replay.json"
    replay.write_text(json.dumps(replay_document([row])), encoding="utf-8")
    asset_path = tmp_path / "assets.json"
    asset_path.write_text(json.dumps(assets()), encoding="utf-8")
    assert (
        main(["quality-report", "--replay", str(replay), "--assets", str(asset_path)])
        == 2
    )
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["builds"][0]["replay"]["summary"]["actions"] == {"buy": 1}
    assert report["replay_sha256"] == sha256_json(replay_document([row]))
    assert "deidentified-match" not in output


def test_quality_assets_are_fingerprint_bound(tmp_path: Path) -> None:
    path = tmp_path / "assets.json"
    rows = assets()
    evidence = replace(catalog(), items_sha256=sha256_json(rows))
    path.write_text(json.dumps(rows), encoding="utf-8")
    assert load_replay_assets(path, evidence) == rows
    rows[0]["cost"] = 1
    path.write_text(json.dumps(rows), encoding="utf-8")
    with pytest.raises(RecommendationError, match="pinned evidence"):
        load_replay_assets(path, evidence)
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(RecommendationError, match="list of objects"):
        load_replay_assets(path, evidence)


def test_quality_bundle_rejects_changed_snapshot(tmp_path: Path) -> None:
    context_path, _, _, _ = _write_bundle(tmp_path)
    document = json.loads(context_path.read_bytes())
    document["snapshot_manifest"]["client_version"] = 999
    context_path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match=r"snapshot|edited|identity"):
        load_quality_inputs(tmp_path)
