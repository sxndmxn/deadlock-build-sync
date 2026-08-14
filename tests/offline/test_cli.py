from argparse import Namespace
from pathlib import Path

import pytest

import deadlock_build_sync.offline.cli as cli_module
from deadlock_build_sync.offline.cli import (
    _check_explicit_cohort_args,
    _cohort_from_manifest,
    _file_sha256,
    build_parser,
)


def _manifest() -> dict[str, object]:
    return {
        "cohort": {
            "minimum_badge": 71,
            "maximum_badge": 115,
            "since": "2026-07-30T19:14:37+00:00",
            "as_of": "2026-08-09T13:21:24+00:00",
            "match_mode": "Ranked",
            "game_mode": "Normal",
        }
    }


def test_existing_manifest_restores_frozen_cohort() -> None:
    cohort = _cohort_from_manifest(_manifest())

    assert cohort.minimum_badge == 71
    assert cohort.maximum_badge == 115
    assert cohort.resolved_as_of().isoformat() == "2026-08-09T13:21:24+00:00"


def test_unspecified_existing_cohort_arguments_do_not_conflict() -> None:
    args = Namespace(min_rank=None, max_rank=None, since=None, as_of=None)

    _check_explicit_cohort_args(args, _cohort_from_manifest(_manifest()))


def test_conflicting_existing_cohort_requires_new_run_id() -> None:
    args = Namespace(min_rank=81, max_rank=None, since=None, as_of=None)

    with pytest.raises(SystemExit, match="new --run-id"):
        _check_explicit_cohort_args(args, _cohort_from_manifest(_manifest()))


def test_file_sha256_is_stable(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.parquet"
    artifact.write_bytes(b"frozen cohort")

    assert (
        _file_sha256(artifact)
        == "8b38cf84a582c3367db23337dfe6fe51fc062d15d25cde64d9162f8db8ff3738"
    )


def test_installed_package_identity_does_not_require_a_git_checkout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.setattr(cli_module, "PACKAGE_ROOT", tmp_path)
    monkeypatch.setattr(cli_module, "PRODUCTION_REPO", tmp_path)

    identity = cli_module._repo_identity()

    assert identity["status"] == "installed-package"
    assert len(identity["tracked_index_sha256"]) == 64


def test_layout_command_accepts_explicit_hero_and_threshold() -> None:
    args = build_parser().parse_args([
        "layout",
        "--run-id",
        "frozen",
        "--hero-id",
        "13",
        "--hero-name",
        "Haze",
        "--minimum-net-worth",
        "45000",
    ])

    assert args.command == "layout"
    assert args.hero_id == 13
    assert args.hero_name == "Haze"
    assert args.minimum_net_worth == 45_000


def test_xgboost_command_accepts_resource_limits() -> None:
    args = build_parser().parse_args([
        "xgboost",
        "--run-id",
        "frozen",
        "--xgb-train-queries",
        "1000",
        "--xgb-test-queries",
        "500",
    ])

    assert args.command == "xgboost"
    assert args.xgb_train_queries == 1000
    assert args.xgb_test_queries == 500
