from __future__ import annotations

import json
from pathlib import Path

import pytest

import deadlock_build_sync.cli as cli_module
from deadlock_build_sync.presentation import build_presentation
from deadlock_build_sync.protobuf import encode_hero_build
from deadlock_build_sync.purchase_guide import PurchaseGuide
from deadlock_build_sync.ranks import RankDivision
from deadlock_build_sync.renderer import projection_fingerprint
from deadlock_build_sync.tracing import (
    TRACE_ENVIRONMENT_VARIABLE,
    TRACE_FILE_NAME,
    TRACE_RETENTION_RUNS,
    TraceMode,
    TraceSession,
    record_stage_facts,
    render_trace_summary,
)


def _events(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _guide() -> PurchaseGuide:
    return PurchaseGuide(
        hero_id=12,
        hero_name="Kelvin",
        hero_class_name="hero_kelvin",
        tiers={1: (), 2: (), 3: (), 4: ()},
        summary="Evidence default.",
        snapshot_id="s" * 64,
        policy_id="p" * 64,
        client_version=123,
        match_mode="ranked",
        rank_identity="oracle-iii–eternus-v",
        build_tag_ids=(1, 2, 3),
        as_of_timestamp=999,
    )


def test_call_trace_records_balanced_project_calls_without_values(
    tmp_path: Path,
) -> None:
    private_value = "do-not-record-this-value"
    session = TraceSession(TraceMode.CALLS, "fixture", root=tmp_path)

    with session:
        assert RankDivision.parse("III") == RankDivision.THREE
        with pytest.raises(ValueError, match="not in tuple"):
            RankDivision.parse(private_value)
        session.finish(0)

    assert session.path is not None
    raw = session.path.read_text(encoding="utf-8")
    events = _events(session.path)
    calls = {event["call_id"] for event in events if event.get("event") == "call"}
    returns = {event["call_id"] for event in events if event.get("event") == "return"}

    assert calls
    assert calls == returns
    assert any(event.get("event") == "exception" for event in events)
    assert private_value not in raw
    assert "args" not in raw
    assert "return_value" not in raw
    definitions = [
        event for event in events if event.get("event") == "function_definition"
    ]
    assert definitions
    assert all(
        str(event.get("module", "")).startswith("deadlock_build_sync")
        for event in definitions
    )
    assert all(
        "module" not in event for event in events if event.get("event") == "call"
    )


def test_stage_trace_covers_presentation_and_protobuf_with_safe_facts(
    tmp_path: Path,
) -> None:
    guide = _guide()
    session = TraceSession(TraceMode.STAGES, "preview", root=tmp_path)

    with session:
        presentation = build_presentation(
            guide,
            patch_title="Patch",
            patch_published_at="2026-08-15T00:00:00Z",
        )
        encoded = encode_hero_build(
            presentation,
            build_id=1,
            account_id=7654321,
            timestamp=0,
        )
        record_stage_facts(
            "preview.output",
            artifact_id="a" * 64,
            guide_count=1,
            path=tmp_path / "userdata/7654321/artifact.json",
        )
        session.finish(0)

    assert encoded
    assert session.path is not None
    raw = session.path.read_text(encoding="utf-8")
    events = _events(session.path)
    stages = {
        event.get("stage") for event in events if event.get("event") == "stage_start"
    }

    assert {"presentation", "protobuf.serialization"} <= stages
    assert any(event.get("event") == "stage_facts" for event in events)
    assert "7654321" not in raw
    assert "account_id" not in raw
    assert "<numeric-id>" in raw


def test_call_tracing_does_not_change_projection_or_serialization(
    tmp_path: Path,
) -> None:
    guide = _guide()
    presentation = build_presentation(
        guide,
        patch_title="Patch",
        patch_published_at="2026-08-15T00:00:00Z",
    )
    expected_fingerprint = projection_fingerprint(guide)
    expected_protobuf = encode_hero_build(
        presentation,
        build_id=1,
        account_id=2,
        timestamp=3,
    )

    session = TraceSession(TraceMode.CALLS, "preview", root=tmp_path)
    with session:
        traced_fingerprint = projection_fingerprint(guide)
        traced_protobuf = encode_hero_build(
            presentation,
            build_id=1,
            account_id=2,
            timestamp=3,
        )
        session.finish(0)

    assert traced_fingerprint == expected_fingerprint
    assert traced_protobuf == expected_protobuf


def test_call_trace_is_bounded_and_summary_reports_truncation(tmp_path: Path) -> None:
    session = TraceSession(
        TraceMode.CALLS,
        "fixture",
        root=tmp_path,
        max_bytes=700,
    )

    with session:
        for _ in range(20):
            RankDivision.parse("III")
        session.finish(0)

    assert session.path is not None
    assert session.path.stat().st_size <= 700
    assert session.truncated
    summary = render_trace_summary(session.path)
    assert "reached its size limit" in summary


def test_trace_summary_renders_tree_and_per_function_time(tmp_path: Path) -> None:
    session = TraceSession(TraceMode.CALLS, "fixture", root=tmp_path)
    with session:
        RankDivision.parse("III")
        session.finish(0)

    assert session.directory is not None
    summary = render_trace_summary(session.directory)

    assert "Call tree:" in summary
    assert "deadlock_build_sync.ranks.RankDivision.parse" in summary
    assert "Per-function inclusive time:" in summary


def test_trace_retention_keeps_latest_three_and_ignores_unowned_paths(
    tmp_path: Path,
) -> None:
    root = tmp_path / "traces"
    root.mkdir()
    old_runs = []
    for second in range(5):
        run = root / f"20260101T00000{second}.000000Z-100"
        run.mkdir()
        (run / TRACE_FILE_NAME).write_text("{}\n", encoding="utf-8")
        old_runs.append(run)
    unrelated = root / "notes"
    unrelated.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / TRACE_FILE_NAME).write_text("{}\n", encoding="utf-8")
    linked = root / "20260101T000009.000000Z-100"
    linked.symlink_to(outside, target_is_directory=True)

    session = TraceSession(TraceMode.STAGES, "fixture", root=root)
    with session:
        session.finish(0)

    retained = [
        path for path in root.iterdir() if path.is_dir() and not path.is_symlink()
    ]
    assert len([path for path in retained if path != unrelated]) == TRACE_RETENTION_RUNS
    assert all(not path.exists() for path in old_runs[:3])
    assert all(path.exists() for path in old_runs[3:])
    assert unrelated.is_dir()
    assert linked.is_symlink()
    assert (outside / TRACE_FILE_NAME).is_file()


def test_cli_accepts_trace_before_or_after_command_and_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser = cli_module.build_parser()
    assert parser.parse_args(["--trace", "calls", "status"]).trace == TraceMode.CALLS
    assert parser.parse_args(["status", "--trace", "stages"]).trace == TraceMode.STAGES

    monkeypatch.setenv(TRACE_ENVIRONMENT_VARIABLE, "calls")
    assert cli_module.build_parser().parse_args(["status"]).trace == TraceMode.CALLS


def test_cli_trace_preserves_stdout_and_prints_run_directory_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state_home = tmp_path / "state"
    monkeypatch.setenv("XDG_STATE_HOME", str(state_home))
    monkeypatch.delenv(TRACE_ENVIRONMENT_VARIABLE, raising=False)
    monkeypatch.setattr(cli_module, "_run_status", lambda _args: 0)

    assert cli_module.main(["status", "--trace", "calls"]) == 0

    captured = capsys.readouterr()
    assert not captured.out
    assert captured.err.count("Trace: ") == 1
    trace_directory = Path(captured.err.removeprefix("Trace: ").strip())
    assert trace_directory.parent == state_home / "deadlock-build-sync/traces"
    assert (trace_directory / TRACE_FILE_NAME).is_file()
