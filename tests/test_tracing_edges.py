from __future__ import annotations

import inspect
import json
import os
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from deadlock_build_sync import tracing_core, tracing_session, tracing_summary
from deadlock_build_sync.snapshot import sha256_json
from deadlock_build_sync.tracing import (
    TRACE_FILE_NAME,
    TraceError,
    TraceMode,
    TraceSession,
    record_stage_facts,
    render_trace_summary,
    state_directory,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import FrameType
    from typing import TextIO


class _BrokenOutput:
    def __init__(self, *, fail_write: bool = False, fail_close: bool = False) -> None:
        self.fail_write = fail_write
        self.fail_close = fail_close

    def write(self, _value: str) -> int:
        if self.fail_write:
            raise OSError("write failed")
        return 0

    def close(self) -> None:
        if self.fail_close:
            raise OSError("close failed")


def _frame() -> FrameType:
    frame = inspect.currentframe()
    if frame is None or frame.f_back is None:
        raise RuntimeError("Python did not expose the current frame")
    return frame.f_back


def _span(span_id: int = 1, *, stage: str | None = None) -> tracing_session._ActiveSpan:
    return tracing_session._ActiveSpan(
        span_id=span_id,
        parent_id=None,
        depth=0,
        module="deadlock_build_sync.fixture",
        function="fixture",
        stage=stage,
        started_ns=1,
    )


def _write_events(path: Path, events: list[object]) -> None:
    path.write_text(
        "".join(f"{json.dumps(event)}\n" for event in events),
        encoding="utf-8",
    )


def test_trace_mode_state_path_and_fact_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert TraceMode.parse(" CALLS ") == TraceMode.CALLS
    with pytest.raises(TraceError, match="must be one of"):
        TraceMode.parse("full")

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    assert state_directory() == tmp_path / "state/deadlock-build-sync"
    monkeypatch.delenv("XDG_STATE_HOME")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert state_directory() == tmp_path / ".local/state/deadlock-build-sync"

    assert tracing_core._normalize_stage_fact("path", "runs/123456/output.json") == (
        "runs/<numeric-id>/output.json"
    )
    truth_value: object = True
    assert tracing_core._normalize_stage_fact("created", truth_value) is True
    assert tracing_core._normalize_stage_fact("created", None) is None
    assert tracing_core._normalize_stage_fact("created", tmp_path) == str(tmp_path)
    with pytest.raises(TraceError, match="must be paths"):
        tracing_core._normalize_stage_fact("created", 1.5)
    assert tracing_core._sanitize_path("account-123456/file") == (
        "account-<numeric-id>/file"
    )
    assert tracing_core._exception_name(ValueError) == "builtins.ValueError"


def test_inactive_trace_directory_checks_markers_and_links(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = tmp_path / "20260101T000000.000000Z-100"
    run.mkdir()
    (run / TRACE_FILE_NAME).write_text("{}\n", encoding="utf-8")
    assert tracing_core._is_inactive_trace_directory(run)

    marker = run / ".active"
    marker.write_text("bad", encoding="ascii")
    assert not tracing_core._is_inactive_trace_directory(run)
    marker.write_text("999999", encoding="ascii")
    monkeypatch.setattr(os, "kill", _dead_process)
    assert tracing_core._is_inactive_trace_directory(run)
    monkeypatch.setattr(os, "kill", _hidden_process)
    assert not tracing_core._is_inactive_trace_directory(run)

    unrelated = tmp_path / "notes"
    unrelated.mkdir()
    assert not tracing_core._is_inactive_trace_directory(unrelated)
    linked = tmp_path / "20260101T000001.000000Z-100"
    linked.symlink_to(run, target_is_directory=True)
    assert not tracing_core._is_inactive_trace_directory(linked)
    (run / TRACE_FILE_NAME).unlink()
    (run / TRACE_FILE_NAME).symlink_to(tmp_path / "missing")
    assert not tracing_core._is_inactive_trace_directory(run)


def _dead_process(_process_id: int, _signal: int) -> None:
    raise ProcessLookupError


def _hidden_process(_process_id: int, _signal: int) -> None:
    raise PermissionError


def _project_fixture(_frame_value: FrameType) -> str:
    return "deadlock_build_sync.fixture"


def _fail_iterdir(_path: Path) -> Iterator[Path]:
    raise OSError("cannot list")


def _fail_remove(_path: Path) -> None:
    raise OSError("cannot remove")


def test_json_lines_writer_handles_limits_and_io_failures(tmp_path: Path) -> None:
    with pytest.raises(TraceError, match="positive"):
        tracing_core._JsonLinesWriter(tmp_path / "invalid.jsonl", max_bytes=0)

    writer = tracing_core._JsonLinesWriter(tmp_path / "trace.jsonl", max_bytes=90)
    writer.write({"event": "x", "payload": "x" * 200})
    writer.write({"event": "ignored"})
    writer.close()
    assert writer.truncated
    assert writer.bytes_written <= 90

    failed = tracing_core._JsonLinesWriter(tmp_path / "failed.jsonl", max_bytes=1_000)
    failed._output.close()
    failed._output = cast("TextIO", _BrokenOutput(fail_write=True))
    failed.write({"event": "x"})
    assert failed.failed
    failed.write({"event": "ignored"})

    close_failed = tracing_core._JsonLinesWriter(
        tmp_path / "close.jsonl", max_bytes=1_000
    )
    close_failed._output.close()
    close_failed._output = cast("TextIO", _BrokenOutput(fail_close=True))
    close_failed.close()
    assert close_failed.failed


def test_trace_session_failure_facts_and_direct_events(tmp_path: Path) -> None:
    session = TraceSession(TraceMode.STAGES, "failure", root=tmp_path / "stage")
    assert not session.truncated
    with pytest.raises(TraceError, match="unsupported"):
        session.record_stage_facts("bad", {"secret": "value"})
    with pytest.raises(RuntimeError, match="boom"):
        _fail_session(session)
    assert session.path is not None
    complete = next(
        event
        for event in _events(session.path)
        if event.get("event") == "trace_complete"
    )
    assert complete["status"] == "failure"
    assert complete["exception_type"] == "builtins.RuntimeError"

    direct = TraceSession(TraceMode.CALLS, "direct", root=tmp_path / "direct")
    direct.path = tmp_path / "direct-events.jsonl"
    direct._writer = tracing_core._JsonLinesWriter(direct.path, max_bytes=10_000)
    frame = _frame()
    active = _span()
    direct._spans[id(frame)] = active
    assert direct._trace_exceptions(frame, "line", None) is not None
    assert direct._trace_exceptions(frame, "exception", (ValueError,)) is not None
    direct._record_return(frame)
    direct._record_return(frame)
    direct._profile(frame, "other", None)
    assert direct._trace_exceptions(frame, "call", None) is None
    first_id = direct._function_id("deadlock_build_sync.fixture", "fixture", frame)
    assert (
        direct._function_id("deadlock_build_sync.fixture", "fixture", frame) == first_id
    )
    direct._writer.close()
    assert any(event.get("event") == "exception" for event in _events(direct.path))

    record_stage_facts("inactive", created=1)


def _fail_session(session: TraceSession) -> None:
    with session:
        session.finish(2)
        raise RuntimeError("boom")


def _events(path: Path) -> list[dict[str, object]]:
    values: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = json.loads(line)
        if isinstance(value, dict):
            values.append(cast("dict[str, object]", value))
    return values


def test_trace_parent_module_and_stage_return_helpers(tmp_path: Path) -> None:
    session = TraceSession(TraceMode.STAGES, "direct", root=tmp_path)
    session.path = tmp_path / "stage-events.jsonl"
    session._writer = tracing_core._JsonLinesWriter(session.path, max_bytes=10_000)
    parent_frame = _frame()
    parent = _span(1, stage="parent")
    session._spans[id(parent_frame)] = parent

    def child_parent() -> tracing_session._ActiveSpan | None:
        return session._project_parent(_frame())

    assert child_parent() is parent
    child_frame = _frame()
    child = _span(2, stage="child")
    child.exception_pending = True
    child.exception_type = "builtins.ValueError"
    session._spans[id(child_frame)] = child
    session._record_return(child_frame)
    session._writer.close()

    assert tracing_core._project_module(parent_frame) is None
    assert tracing_core._module_file(
        "deadlock_build_sync.fixture", parent_frame
    ).endswith("deadlock_build_sync/fixture.py")
    assert any(event.get("event") == "stage_end" for event in _events(session.path))


def test_trace_session_direct_exit_and_global_facts(tmp_path: Path) -> None:
    session = TraceSession(TraceMode.STAGES, "direct-exit", root=tmp_path)
    session.path = tmp_path / "exit.jsonl"
    session._writer = tracing_core._JsonLinesWriter(session.path, max_bytes=10_000)
    session._started_ns = 1
    session._previous_profile = cast(
        "tracing_session._ProfileHook | None", sys.getprofile()
    )
    session._previous_trace = cast("tracing_session._TraceHook | None", sys.gettrace())
    session._active_marker = tmp_path / ".active"
    session._active_marker.write_text("1", encoding="ascii")
    session._context_token = tracing_session._ACTIVE_TRACE.set(session)
    session.record_stage_facts("stage", {"created": 1})
    record_stage_facts("global", updated=2)
    session.finish(2)

    session.__exit__(ValueError, ValueError("bad"), None)

    events = _events(session.path)
    assert any(event.get("stage") == "global" for event in events)
    assert events[-1]["status"] == "failure"
    assert not (tmp_path / ".active").exists()

    empty = TraceSession(TraceMode.CALLS, "empty", root=tmp_path / "empty")
    empty._write({"event": "ignored"})


def test_trace_call_recording_and_stage_exception_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tracing_session, "_project_module", _project_fixture)
    monkeypatch.setattr(
        tracing_session,
        "_module_file",
        lambda *_args: "deadlock_build_sync/fixture.py",
    )
    timestamps = iter((100, 150, 200, 260))
    monkeypatch.setattr(
        tracing_session.time,
        "perf_counter_ns",
        lambda: next(timestamps),
    )
    frame = _frame()
    calls = TraceSession(TraceMode.CALLS, "calls", root=tmp_path)
    calls.path = tmp_path / "calls.jsonl"
    calls._writer = tracing_core._JsonLinesWriter(calls.path, max_bytes=10_000)
    calls._profile(frame, "call", None)
    assert calls._trace_exceptions(frame, "call", None) is not None
    calls._profile(frame, "return", None)
    calls._writer.close()
    call_events = _events(calls.path)

    stages = TraceSession(TraceMode.STAGES, "stages", root=tmp_path)
    stages.path = tmp_path / "stages.jsonl"
    stages._writer = tracing_core._JsonLinesWriter(stages.path, max_bytes=10_000)
    stages._record_call(frame)
    qualified = f"deadlock_build_sync.fixture.{frame.f_code.co_qualname}"
    monkeypatch.setitem(tracing_session._STAGE_BOUNDARIES, qualified, "fixture")
    stages._record_call(frame)
    assert stages._trace_exceptions(frame, "exception", ()) is not None
    stages._record_return(frame)
    stages._writer.close()
    stage_events = _events(stages.path)
    assert sha256_json({"calls": call_events, "stages": stage_events}) == (
        "656c0bbb7552f1fe4af6145bd74184959402988fc54f3e02b0d222ebb195e66e"
    )


def test_trace_directory_collision_and_prune_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_mkdir = Path.mkdir
    collisions = 0

    def collide_once(
        path: Path,
        mode: int = 0o777,
        *,
        parents: bool = False,
        exist_ok: bool = False,
    ) -> None:
        nonlocal collisions
        if path.parent == tmp_path and path != tmp_path and collisions == 0:
            collisions += 1
            raise FileExistsError
        original_mkdir(path, mode=mode, parents=parents, exist_ok=exist_ok)

    session = TraceSession(TraceMode.STAGES, "collision", root=tmp_path)
    monkeypatch.setattr(Path, "mkdir", collide_once)
    allocated = session._create_directory()
    assert collisions == 1
    assert allocated.name.endswith("-1")

    monkeypatch.setattr(Path, "iterdir", _fail_iterdir)
    session._prune_old_runs()
    monkeypatch.undo()

    prune_root = tmp_path / "prune"
    prune_root.mkdir()
    for second in range(3):
        run = prune_root / f"20260101T00000{second}.000000Z-100"
        run.mkdir()
        (run / TRACE_FILE_NAME).write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(shutil, "rmtree", _fail_remove)
    TraceSession(TraceMode.STAGES, "prune", root=prune_root)._prune_old_runs()
    assert len(list(prune_root.iterdir())) == 3


def test_trace_summary_handles_stage_limits_legacy_calls_and_durations(
    tmp_path: Path,
) -> None:
    stage_path = tmp_path / "stage.jsonl"
    _write_events(
        stage_path,
        [
            {"event": "trace_start", "mode": "stages", "command": "sync"},
            {"event": "stage_start", "stage_id": 1, "stage": "one"},
            {
                "event": "stage_end",
                "stage_id": 1,
                "elapsed_ns": 500,
                "status": "success",
            },
            {"event": "stage_start", "stage_id": 2, "stage": "two", "depth": 1},
            {"event": "trace_truncated"},
            {"event": "trace_complete", "status": "failure", "elapsed_ns": 2_000},
        ],
    )
    summary = render_trace_summary(stage_path, max_nodes=1)

    legacy = tmp_path / "legacy.jsonl"
    _write_events(
        legacy,
        [
            {"event": "trace_start", "mode": "calls"},
            {
                "event": "call",
                "call_id": 1,
                "module": "deadlock_build_sync.old",
                "function": "run",
            },
            {"event": "return", "call_id": 1, "elapsed_ns": 1_000_000},
        ],
    )
    legacy_summary = render_trace_summary(legacy)
    assert (
        sha256_json({
            "stage": summary.replace(str(stage_path), "<trace>"),
            "legacy": legacy_summary.replace(str(legacy), "<trace>"),
        })
        == "ef3c83a3fcb788df04966f46304f0d4dde4a7b3b5495703cb0e733c80accd9a5"
    )
    assert tracing_summary._format_duration(None) == "incomplete"
    assert tracing_summary._format_duration(999) == "999ns"
    assert tracing_summary._format_duration(1_000) == "1.000us"
    assert tracing_summary._format_duration(1_000_000) == "1.000ms"
    assert tracing_summary._format_duration(1_000_000_000) == "1.000s"


@pytest.mark.parametrize(
    ("events", "message"),
    [
        ([[]], "not a JSON object"),
        ([{"event": "function_definition", "function_id": "bad"}], "definition"),
        ([{"event": "call", "call_id": "bad"}], "invalid call"),
        ([{"event": "call", "call_id": 1, "function_id": 9}], "unknown function"),
        ([{"event": "stage_start", "stage_id": "bad"}], "invalid stage"),
    ],
)
def test_trace_summary_rejects_invalid_events(
    tmp_path: Path,
    events: list[object],
    message: str,
) -> None:
    path = tmp_path / f"invalid-{message.replace(' ', '-')}.jsonl"
    _write_events(path, events)

    with pytest.raises(TraceError, match=message):
        render_trace_summary(path)


def test_trace_summary_rejects_invalid_json_limits_and_paths(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed.jsonl"
    malformed.write_text("{\n", encoding="utf-8")
    with pytest.raises(TraceError, match="not valid JSON"):
        tracing_summary._read_trace_summary(malformed)
    with pytest.raises(TraceError, match="positive"):
        render_trace_summary(malformed, max_nodes=0)
    with pytest.raises(TraceError, match="does not exist"):
        render_trace_summary(tmp_path / "missing")
