from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import deadlock_build_sync.freshness as freshness_module
from deadlock_build_sync.api import Patch
from deadlock_build_sync.freshness import (
    FreshnessError,
    FreshnessReport,
    FreshnessStage,
    FreshnessState,
    build_freshness_report,
    require_current_build_evidence,
)


class FakeApi:
    def __init__(self, client_version: int = 123) -> None:
        self.client_version = client_version
        self.patch = Patch("Patch", 100, "2026-01-01T00:00:00Z")

    def resolve_client_version(self) -> int:
        return self.client_version

    def current_patch(self) -> Patch:
        return self.patch


def evidence(api: FakeApi) -> Any:
    return SimpleNamespace(
        client_version=api.client_version,
        patch={"identity": api.patch.identity},
        artifact_id="a" * 64,
    )


def test_current_evidence_is_returned_and_stale_evidence_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = FakeApi()
    current = evidence(api)
    monkeypatch.setattr(freshness_module, "load_build_evidence", lambda _path: current)

    assert require_current_build_evidence(tmp_path / "evidence.json", api) is current

    current.client_version = 122
    with pytest.raises(FreshnessError, match="STALE — regeneration required"):
        require_current_build_evidence(tmp_path / "evidence.json", api)


def test_missing_and_malformed_artifact_chains_have_distinct_exit_codes(
    tmp_path: Path,
) -> None:
    api = FakeApi()

    missing = build_freshness_report(tmp_path, api)
    assert missing.exit_code == 1
    assert missing.as_dict()["status"] == "invalid_or_unavailable"
    assert missing.stages[0].state is FreshnessState.MISSING
    assert missing.stages[-1].state is FreshnessState.UNAVAILABLE

    (tmp_path / "build-evidence.json").write_text("not-json", encoding="utf-8")
    malformed = build_freshness_report(tmp_path, api)
    assert malformed.exit_code == 1
    assert malformed.stages[0].state is FreshnessState.MALFORMED


def test_report_exit_code_two_means_regeneration_only() -> None:
    report = FreshnessReport(
        (FreshnessStage("build_evidence", FreshnessState.STALE, "old patch"),),
        123,
        FakeApi().patch,
    )

    assert report.exit_code == 2
    assert report.as_dict()["status"] == "regeneration_required"
