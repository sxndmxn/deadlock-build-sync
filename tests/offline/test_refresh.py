from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from deadlock_build_sync.build_evidence import METHOD_VERSION
from deadlock_build_sync.cli_parser import build_parser
from deadlock_build_sync.offline import refresh
from deadlock_build_sync.offline.api import read_json, write_json
from deadlock_build_sync.offline.config import RunPaths
from deadlock_build_sync.value_validation import require_object_dict

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("worker_arguments", "workers"), [([], 8), (["--workers", "3"], 3)]
)
def test_refresh_uses_requested_worker_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    worker_arguments: list[str],
    workers: int,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setattr(refresh, "capture_sources", lambda _paths: {})
    monkeypatch.setattr(
        refresh, "_select_patch_at_timestamp", lambda *_args: {"start_timestamp": 1}
    )
    monkeypatch.setattr(refresh, "extract_cohort", lambda *_args, **_kwargs: {})
    output = tmp_path / "build-evidence.json"
    received: list[int] = []

    def export_evidence(
        paths: RunPaths, target: Path, *, workers: int, resume: bool, generator: str
    ) -> dict[str, object]:
        assert target == output
        assert resume is False
        assert generator == "current"
        assert (paths.run / "manifest.json").exists()
        received.append(workers)
        return {"artifact_id": "test"}

    monkeypatch.setattr(refresh, "export_production_evidence", export_evidence)
    assert refresh.main(["--output", str(output), *worker_arguments]) == 0
    assert received == [workers]


@pytest.mark.parametrize("workers", ["0", "-1", "invalid"])
def test_refresh_rejects_invalid_worker_count(tmp_path: Path, workers: str) -> None:
    with pytest.raises(SystemExit) as public_error:
        build_parser().parse_args(["refresh-evidence", "--workers", workers])
    assert public_error.value.code == 2
    with pytest.raises(SystemExit) as offline_error:
        refresh.main(["--output", str(tmp_path / "output.json"), "--workers", workers])
    assert offline_error.value.code == 2


def _saved_source_run(tmp_path: Path) -> RunPaths:
    paths = RunPaths.create(tmp_path / "deadlock-build-sync/offline", "saved")
    write_json(
        paths.run / "manifest.json",
        {
            "schema_version": 2,
            "production_method": "eclat_leiden_pairwise",
            "method_version": METHOD_VERSION,
            "test_usage": "reserved",
            "rank_expansion": "off",
            "cohort": {
                "minimum_badge": 71,
                "maximum_badge": 115,
                "since": "2026-08-22T00:00:00+00:00",
                "as_of": "2026-09-09T00:00:00+00:00",
            },
            "extraction": {"heroes": 38},
        },
    )
    (paths.raw / "analysis.duckdb").touch()
    return paths


def test_resume_reuses_source_run_without_capture_or_extraction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    paths = _saved_source_run(tmp_path)
    manifest = paths.run / "manifest.json"
    previous = manifest.read_bytes()

    def reject_source_refresh(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise AssertionError("Resume must preserve source data")

    def export_evidence(
        resumed: RunPaths, _output: Path, *, workers: int, resume: bool, generator: str
    ) -> dict[str, object]:
        assert resumed == paths
        assert workers == 8
        assert resume is True
        assert generator == "current"
        return {"artifact_id": "test"}

    monkeypatch.setattr(refresh, "capture_sources", reject_source_refresh)
    monkeypatch.setattr(refresh, "extract_cohort", reject_source_refresh)
    monkeypatch.setattr(refresh, "export_production_evidence", export_evidence)
    assert (
        refresh.main([
            "--output",
            str(tmp_path / "output.json"),
            "--run-id",
            "saved",
            "--rank-expansion",
            "off",
            "--resume",
            "--as-of",
            "2026-09-09T00:00:00Z",
        ])
        == 0
    )
    assert manifest.read_bytes() == previous


@pytest.mark.parametrize("version", [None, "eclat-leiden-pairwise-v3"])
def test_resume_rejects_sources_from_previous_sql_validation_rules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, version: str | None
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    paths = _saved_source_run(tmp_path)
    manifest = require_object_dict(read_json(paths.run / "manifest.json"))
    if version is None:
        manifest.pop("method_version")
    else:
        manifest["method_version"] = version
    write_json(paths.run / "manifest.json", manifest)
    with pytest.raises(ValueError, match="Source extraction method differs"):
        refresh.main([
            "--output",
            str(tmp_path / "output.json"),
            "--run-id",
            "saved",
            "--rank-expansion",
            "off",
            "--resume",
        ])


@pytest.mark.parametrize(
    "arguments",
    [
        ["--rank-expansion", "auto"],
        ["--min-rank", "81"],
        ["--max-rank", "111"],
        ["--since", "2026-08-23T00:00:00Z"],
        ["--as-of", "2026-09-08T00:00:00Z"],
    ],
)
def test_resume_rejects_changed_cohort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, arguments: list[str]
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    _saved_source_run(tmp_path)
    with pytest.raises(ValueError, match="options must match"):
        refresh.main([
            "--output",
            str(tmp_path / "output.json"),
            "--run-id",
            "saved",
            "--rank-expansion",
            "off",
            "--resume",
            *arguments,
        ])


def test_resume_requires_run_id_and_completed_extraction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    output = ["--output", str(tmp_path / "output.json")]
    with pytest.raises(SystemExit) as error:
        refresh.main([*output, "--resume"])
    assert error.value.code == 2
    paths = _saved_source_run(tmp_path)
    (paths.raw / "analysis.duckdb").unlink()
    with pytest.raises(ValueError, match="completed production source extraction"):
        refresh.main([
            *output,
            "--run-id",
            "saved",
            "--rank-expansion",
            "off",
            "--resume",
        ])
    with pytest.raises(ValueError, match="new --run-id"):
        refresh.main([*output, "--run-id", "saved"])
