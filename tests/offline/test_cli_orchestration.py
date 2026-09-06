from __future__ import annotations

import json
from argparse import Namespace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from deadlock_build_sync.offline.config import Cohort, RunPaths, sha256_json
from tools.comparisons.legacy import cli

if TYPE_CHECKING:
    from pathlib import Path


def _cohort() -> Cohort:
    return Cohort(
        since=datetime(2026, 8, 1, tzinfo=UTC),
        as_of=datetime(2026, 8, 2, tzinfo=UTC),
    )


def _paths(tmp_path: Path) -> RunPaths:
    return RunPaths.create(tmp_path, "run")


def _touch(paths: RunPaths, *relative_paths: str) -> None:
    for relative in relative_paths:
        path = paths.run / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("data", encoding="utf-8")


def test_repo_identity_reads_git_status_and_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "PRODUCTION_REPO", tmp_path)
    monkeypatch.setattr(cli, "PACKAGE_ROOT", tmp_path / "package")
    monkeypatch.setattr(cli.shutil, "which", lambda _name: "/usr/bin/git")
    calls: list[tuple[list[str], dict[str, object]]] = []

    def run(command: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append((command, kwargs))
        output: str | bytes = "## main\n" if "status" in command else b"index"
        return SimpleNamespace(stdout=output)

    monkeypatch.setattr(cli.subprocess, "run", run)

    identity = cli._repo_identity()

    assert identity == {
        "status": "## main",
        "tracked_index_sha256": (
            "1bc04b5291c26a46d918139138b992d2de976d6851d0893b0476b85bfbdfc6e6"
        ),
    }
    common_options = {
        "cwd": tmp_path,
        "check": True,
        "capture_output": True,
        "shell": False,
    }
    assert calls == [
        (
            ["/usr/bin/git", "status", "--short", "--branch"],
            {**common_options, "text": True},
        ),
        (["/usr/bin/git", "ls-files", "-s"], common_options),
    ]


def test_repo_identity_requires_git(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "PRODUCTION_REPO", tmp_path)
    monkeypatch.setattr(cli, "PACKAGE_ROOT", tmp_path / "package")
    monkeypatch.setattr(cli.shutil, "which", lambda _name: None)

    with pytest.raises(RuntimeError, match="git is required"):
        cli._repo_identity()


def test_manifest_creates_new_document_and_rejects_non_object(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _paths(tmp_path)
    generated_at = datetime(2026, 1, 2, tzinfo=UTC)

    class FixedDatetime:
        @staticmethod
        def now(**_kwargs: object) -> datetime:
            return generated_at

    monkeypatch.setattr(cli, "datetime", FixedDatetime)
    monkeypatch.setattr(cli, "PRODUCTION_REPO", tmp_path / "repo")
    manifest = cli._manifest(paths, _cohort())

    stable = {
        **manifest,
        "project_root": "<root>",
        "producer_source": "<repo>",
    }
    assert sha256_json(stable) == (
        "0f9a36acf3c03c54b850d99362891d8ddfee4948e3535eb04d4afc7e217b7637"
    )

    (paths.run / "manifest.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(cli, "read_json", lambda _path: [])
    with pytest.raises(SystemExit, match="not an object"):
        cli._manifest(paths, _cohort())


@pytest.mark.parametrize(
    ("manifest", "message"),
    [
        ({}, "no valid frozen cohort"),
        (
            {
                "cohort": {
                    "minimum_badge": 71,
                    "maximum_badge": 115,
                    "since": "bad",
                    "as_of": "bad",
                }
            },
            "incomplete cohort timestamps",
        ),
    ],
)
def test_cohort_from_manifest_rejects_invalid_data(
    manifest: dict[str, object],
    message: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if "cohort" in manifest:
        monkeypatch.setattr(cli, "parse_timestamp", lambda _value: None)

    with pytest.raises(SystemExit, match=message):
        cli._cohort_from_manifest(manifest)


def test_cohort_from_manifest_uses_mode_defaults() -> None:
    cohort = cli._cohort_from_manifest({
        "cohort": {
            "minimum_badge": 71,
            "maximum_badge": 115,
            "since": "2026-08-01T00:00:00+00:00",
            "as_of": "2026-08-02T00:00:00+00:00",
        }
    })

    assert cohort.match_mode == "Ranked"
    assert cohort.game_mode == "Normal"


def test_cache_helpers_hash_data_and_report_missing_files(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    first = paths.data / "first.parquet"
    second = paths.data / "second.parquet"
    first.write_bytes(b"first")
    second.write_bytes(b"second")

    hashes = cli._frozen_data_hashes(paths)

    assert set(hashes) == {"data/first.parquet", "data/second.parquet"}
    assert cli._cache_size(paths) == 11
    cli._require(paths, "data/first.parquet")
    with pytest.raises(SystemExit, match="missing prerequisites: missing"):
        cli._require(paths, "missing")


def test_run_extract_and_audit_update_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _paths(tmp_path)
    _touch(paths, "raw/heroes.json")
    manifest: dict[str, object] = {}
    saved: list[dict[str, object]] = []
    monkeypatch.setattr(cli, "capture_sources", lambda _paths: {"source": True})
    monkeypatch.setattr(cli, "extract_cohort", lambda _paths, _cohort: {"rows": 2})
    monkeypatch.setattr(cli, "capture_api_audit", lambda _paths, _cohort: {"ok": True})
    monkeypatch.setattr(
        cli, "_save_manifest", lambda _paths, value: saved.append(value.copy())
    )

    cli.run_extract(paths, _cohort(), manifest)
    cli.run_audit(paths, _cohort(), manifest)

    assert manifest["sources"] == {"source": True}
    assert manifest["extraction"] == {"rows": 2}
    assert manifest["api_audit"] == {"ok": True}
    assert len(saved) == 2


def test_run_analysis_saves_results_and_enforces_cache_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _paths(tmp_path)
    _touch(paths, "raw/analysis.duckdb")
    paths.api.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {}
    monkeypatch.setattr(cli, "analyze", lambda _paths: {"analysis": True})
    monkeypatch.setattr(cli, "generate_rankings", lambda _paths: {"rankings": True})
    monkeypatch.setattr(cli, "_save_manifest", lambda _paths, _manifest: None)
    monkeypatch.setattr(cli, "_cache_size", lambda _paths: 1)

    cli.run_analysis(paths, manifest)
    assert manifest["rankings"] == {"rankings": True}

    monkeypatch.setattr(cli, "_cache_size", lambda _paths: cli.MAX_CACHE_BYTES + 1)
    with pytest.raises(RuntimeError, match="cap exceeded"):
        cli.run_analysis(paths, manifest)


def test_report_layout_and_export_requests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = _paths(tmp_path)
    _touch(
        paths,
        "tables/item_metrics.csv",
        "tables/top10_rankings.csv",
        "tables/late_game_hero_13_45000.json",
        "tables/late_game_hero_13_45000_items.csv",
        "manifest.json",
        "raw/analysis.duckdb",
        "raw/heroes.json",
        "raw/items.json",
        "raw/items-all.json",
        "raw/patches.json",
        "raw/ranks.json",
    )
    saved: list[dict[str, object]] = []
    monkeypatch.setattr(
        cli, "_save_manifest", lambda _paths, value: saved.append(value.copy())
    )
    monkeypatch.setattr(cli, "render_report", lambda _paths: {"report": True})
    monkeypatch.setattr(
        cli,
        "write_build_layout",
        lambda *_args, **_kwargs: (
            paths.tables / "layout.json",
            paths.tables / "layout.md",
        ),
    )
    monkeypatch.setattr(
        cli,
        "export_production_evidence",
        lambda _paths, _output: {"heroes": [{"id": 13}]},
    )
    manifest: dict[str, object] = {}

    cli.run_report(paths, manifest)
    cli.run_layout(
        paths,
        manifest,
        hero_id=13,
        hero_name="Haze",
        minimum_net_worth=45_000,
    )
    cli.run_export_evidence(paths, tmp_path / "evidence.json")

    assert manifest["reporting"] == {"report": True}
    assert manifest["build_layout"] == {
        "hero_id": 13,
        "hero": "Haze",
        "minimum_net_worth": 45_000,
        "json": "tables/layout.json",
        "markdown": "tables/layout.md",
    }
    assert len(saved) == 3
    assert "Exported 1 heroes" in capsys.readouterr().out


def test_export_rejects_missing_hero_array(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _paths(tmp_path)
    _touch(
        paths,
        "manifest.json",
        "raw/analysis.duckdb",
        "raw/heroes.json",
        "raw/items.json",
        "raw/items-all.json",
        "raw/patches.json",
        "raw/ranks.json",
        "tables/item_metrics.csv",
    )
    monkeypatch.setattr(cli, "export_production_evidence", lambda _paths, _output: {})

    with pytest.raises(RuntimeError, match="no hero array"):
        cli.run_export_evidence(paths, tmp_path / "evidence.json")


def test_request_helpers_validate_required_arguments(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    with pytest.raises(SystemExit, match="layout requires"):
        cli._run_layout_request(
            Namespace(hero_id=None, hero_name=None, minimum_net_worth=45_000),
            paths,
            {},
        )
    with pytest.raises(SystemExit, match="requires --output"):
        cli._run_export_request(Namespace(output=None, command="all"), paths)


def test_execute_command_routes_all_and_layout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _paths(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(cli, "run_extract", lambda *_args: calls.append("extract"))
    monkeypatch.setattr(cli, "run_audit", lambda *_args: calls.append("audit"))
    monkeypatch.setattr(cli, "run_analysis", lambda *_args: calls.append("analyze"))
    monkeypatch.setattr(cli, "run_report", lambda *_args: calls.append("report"))
    monkeypatch.setattr(
        cli, "_run_export_request", lambda *_args: calls.append("export")
    )
    monkeypatch.setattr(
        cli, "_run_layout_request", lambda *_args: calls.append("layout")
    )

    cli._execute_offline_command(Namespace(command="all"), paths, _cohort(), {})
    cli._execute_offline_command(Namespace(command="layout"), paths, _cohort(), {})

    assert calls == ["extract", "audit", "analyze", "report", "export", "layout"]


def test_main_runs_new_and_existing_manifests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    completed_at = datetime(2026, 8, 31, tzinfo=UTC)

    class FixedDatetime:
        @staticmethod
        def now(**_kwargs: object) -> datetime:
            return completed_at

    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(cli, "PRODUCTION_REPO", tmp_path / "repo")
    monkeypatch.setattr(cli, "datetime", FixedDatetime)
    identity = {"status": "clean", "tracked_index_sha256": "a" * 64}
    monkeypatch.setattr(cli, "_repo_identity", lambda: identity)
    monkeypatch.setattr(cli, "_execute_offline_command", lambda *_args: None)

    assert cli.main(["report", "--run-id", "new"]) == 0
    output = json.loads(capsys.readouterr().out)
    output["run"] = "<run>"
    output["manifest"]["project_root"] = "<root>"
    output["manifest"]["producer_source"] = "<repo>"
    assert sha256_json(output) == (
        "b0456db46d82cf79f5efe8648086a075388eec03d464a784e6d04b15f6275752"
    )

    paths = RunPaths.create(tmp_path, "existing")
    cli.write_json(
        paths.run / "manifest.json",
        {
            "cohort": {
                "minimum_badge": 71,
                "maximum_badge": 115,
                "since": "2026-08-01T00:00:00+00:00",
                "as_of": "2026-08-02T00:00:00+00:00",
            }
        },
    )
    assert cli.main(["report", "--run-id", "existing"]) == 0


def test_main_rejects_source_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    identities = iter([
        {"status": "before", "tracked_index_sha256": "a" * 64},
        {"status": "after", "tracked_index_sha256": "b" * 64},
    ])
    monkeypatch.setattr(cli, "_repo_identity", lambda: next(identities))
    monkeypatch.setattr(cli, "_execute_offline_command", lambda *_args: None)

    with pytest.raises(RuntimeError, match="identity changed"):
        cli.main(["report", "--run-id", "changed"])
