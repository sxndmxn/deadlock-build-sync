from __future__ import annotations

import os
import shutil
import sys
import time
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from .tracing_core import (
    _ACTIVE_MARKER_NAME,
    _SAFE_STAGE_FACTS,
    _STAGE_BOUNDARIES,
    DEFAULT_CALL_TRACE_MAX_BYTES,
    TRACE_FILE_NAME,
    TRACE_RETENTION_RUNS,
    TRACE_SCHEMA_VERSION,
    TraceError,
    TraceMode,
    _format_exception_name,
    _is_inactive_trace_directory,
    _JsonLinesWriter,
    _normalize_stage_fact,
    _project_module,
    _resolve_module_filename,
    state_directory,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from types import FrameType, TracebackType
    from typing import Self

    type _ProfileHook = Callable[[FrameType, str, object], object]
    type _TraceHook = Callable[[FrameType, str, object], _TraceHook | None]


@dataclass
class _ActiveSpan:
    span_id: int
    parent_id: int | None
    depth: int
    module: str
    function: str
    stage: str | None
    started_ns: int
    exception_pending: bool = False
    exception_type: str | None = None


_ACTIVE_TRACE: ContextVar[TraceSession | None] = ContextVar(
    "deadlock_build_sync_active_trace",
    default=None,
)


class TraceSession:
    """Record one CLI command without observing application values."""

    def __init__(
        self,
        mode: TraceMode,
        command: str,
        *,
        root: Path | None = None,
        max_bytes: int = DEFAULT_CALL_TRACE_MAX_BYTES,
    ) -> None:
        self.mode = mode
        self.command = command
        self.root = root or state_directory() / "traces"
        self.max_bytes = max_bytes
        self.directory: Path | None = None
        self.path: Path | None = None
        self._writer: _JsonLinesWriter | None = None
        self._started_ns = 0
        self._next_span_id = 1
        self._next_function_id = 1
        self._function_ids: dict[tuple[str, str, str, int], int] = {}
        self._spans: dict[int, _ActiveSpan] = {}
        self._context_token: Token[TraceSession | None] | None = None
        self._previous_profile: _ProfileHook | None = None
        self._previous_trace: _TraceHook | None = None
        self._exit_code: int | None = None
        self._active_marker: Path | None = None

    def __enter__(self) -> Self:
        """Create the trace and install the profiling hooks.

        Returns:
            This active trace session.

        """
        self.directory = self._create_directory()
        self.path = self.directory / TRACE_FILE_NAME
        self._writer = _JsonLinesWriter(self.path, max_bytes=self.max_bytes)
        self._started_ns = time.perf_counter_ns()
        self._write({
            "command": self.command,
            "event": "trace_start",
            "mode": self.mode.value,
            "schema_version": TRACE_SCHEMA_VERSION,
            "started_at": datetime.now(UTC).isoformat(),
        })
        self._context_token = _ACTIVE_TRACE.set(self)
        self._previous_profile = cast("_ProfileHook | None", sys.getprofile())
        self._previous_trace = cast("_TraceHook | None", sys.gettrace())
        sys.setprofile(self._profile)
        sys.settrace(self._trace_exceptions)
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        _exception: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        """Restore prior hooks and close the trace with terminal status."""
        sys.setprofile(self._previous_profile)
        sys.settrace(self._previous_trace)
        elapsed_ns = time.perf_counter_ns() - self._started_ns
        failed = exception_type is not None or (
            self._exit_code is not None and self._exit_code != 0
        )
        event: dict[str, object] = {
            "elapsed_ns": elapsed_ns,
            "event": "trace_complete",
            "exit_code": self._exit_code,
            "schema_version": TRACE_SCHEMA_VERSION,
            "status": "failure" if failed else "success",
        }
        if exception_type is not None:
            event["exception_type"] = _format_exception_name(exception_type)
        self._write(event)
        if self._context_token is not None:
            _ACTIVE_TRACE.reset(self._context_token)
            self._context_token = None
        if self._writer is not None:
            self._writer.close()
        if self._active_marker is not None:
            self._active_marker.unlink(missing_ok=True)
            self._active_marker = None

    def finish(self, exit_code: int) -> None:
        """Record the command result for the terminal trace event."""
        self._exit_code = exit_code

    @property
    def truncated(self) -> bool:
        return self._writer.truncated if self._writer is not None else False

    def record_stage_facts(self, stage: str, facts: dict[str, object]) -> None:
        unexpected = set(facts) - _SAFE_STAGE_FACTS
        if unexpected:
            raise TraceError(
                "unsupported trace fact(s): " + ", ".join(sorted(unexpected))
            )
        normalized = {
            key: _normalize_stage_fact(key, value) for key, value in facts.items()
        }
        self._write({
            "event": "stage_facts",
            "schema_version": TRACE_SCHEMA_VERSION,
            "stage": stage,
            **normalized,
        })

    def _create_directory(self) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        self._prune_old_runs()
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        prefix = f"{timestamp}-{os.getpid()}"
        for collision in range(1000):
            suffix = "" if collision == 0 else f"-{collision}"
            candidate = self.root / f"{prefix}{suffix}"
            try:
                candidate.mkdir()
            except FileExistsError:
                continue
            self._active_marker = candidate / _ACTIVE_MARKER_NAME
            self._active_marker.write_text(str(os.getpid()), encoding="ascii")
            return candidate
        raise TraceError("could not allocate a unique trace directory")

    def _prune_old_runs(self) -> None:
        try:
            candidates = sorted(
                path
                for path in self.root.iterdir()
                if _is_inactive_trace_directory(path)
            )
        except OSError:
            return
        remove_count = max(0, len(candidates) - (TRACE_RETENTION_RUNS - 1))
        for candidate in candidates[:remove_count]:
            try:
                shutil.rmtree(candidate)
            except OSError:
                continue

    def _profile(self, frame: FrameType, event: str, _argument: object) -> None:
        if event == "call":
            self._record_call(frame)
        elif event == "return":
            self._record_return(frame)

    def _trace_exceptions(
        self,
        frame: FrameType,
        event: str,
        argument: object,
    ) -> _TraceHook | None:
        frame_id = id(frame)
        if event == "call":
            return (
                self._trace_exceptions if _project_module(frame) is not None else None
            )
        active = self._spans.get(frame_id)
        if active is None:
            return None
        if event == "line":
            active.exception_pending = False
            active.exception_type = None
        elif event == "exception":
            details = cast("tuple[object, ...]", argument)
            exception_type = details[0] if details else None
            active.exception_pending = True
            active.exception_type = _format_exception_name(exception_type)
            if self.mode == TraceMode.CALLS:
                self._write({
                    "call_id": active.span_id,
                    "event": "exception",
                    "exception_type": active.exception_type,
                })
            else:
                self._write({
                    "event": "stage_exception",
                    "exception_type": active.exception_type,
                    "schema_version": TRACE_SCHEMA_VERSION,
                    "stage": active.stage,
                    "stage_id": active.span_id,
                })
        return self._trace_exceptions

    def _record_call(self, frame: FrameType) -> None:
        module = _project_module(frame)
        if module is None:
            return
        function = frame.f_code.co_qualname
        qualified_name = f"{module}.{function}"
        stage = _STAGE_BOUNDARIES.get(qualified_name)
        if self.mode == TraceMode.STAGES and stage is None:
            return
        parent = self._project_parent(frame)
        span_id = self._next_span_id
        self._next_span_id += 1
        active = _ActiveSpan(
            span_id=span_id,
            parent_id=parent.span_id if parent is not None else None,
            depth=parent.depth + 1 if parent is not None else 0,
            module=module,
            function=function,
            stage=stage,
            started_ns=time.perf_counter_ns(),
        )
        self._spans[id(frame)] = active
        if self.mode == TraceMode.CALLS:
            function_id = self._function_id(module, function, frame)
            self._write({
                "call_id": span_id,
                "event": "call",
                "function_id": function_id,
                "parent_call_id": active.parent_id,
            })
        else:
            self._write({
                "depth": active.depth,
                "event": "stage_start",
                "function": function,
                "module": module,
                "parent_stage_id": active.parent_id,
                "schema_version": TRACE_SCHEMA_VERSION,
                "stage": stage,
                "stage_id": span_id,
            })

    def _record_return(self, frame: FrameType) -> None:
        active = self._spans.pop(id(frame), None)
        if active is None:
            return
        elapsed_ns = time.perf_counter_ns() - active.started_ns
        status = "failure" if active.exception_pending else "success"
        if self.mode == TraceMode.CALLS:
            event: dict[str, object] = {
                "call_id": active.span_id,
                "elapsed_ns": elapsed_ns,
                "event": "return",
                "status": status,
            }
            if active.exception_type is not None:
                event["exception_type"] = active.exception_type
            self._write(event)
        else:
            stage_event: dict[str, object] = {
                "elapsed_ns": elapsed_ns,
                "event": "stage_end",
                "schema_version": TRACE_SCHEMA_VERSION,
                "stage": active.stage,
                "stage_id": active.span_id,
                "status": status,
            }
            if active.exception_type is not None:
                stage_event["exception_type"] = active.exception_type
            self._write(stage_event)

    def _project_parent(self, frame: FrameType) -> _ActiveSpan | None:
        parent = frame.f_back
        while parent is not None:
            active = self._spans.get(id(parent))
            if active is not None:
                return active
            parent = parent.f_back
        return None

    def _function_id(self, module: str, function: str, frame: FrameType) -> int:
        source_file = _resolve_module_filename(module, frame)
        line = frame.f_code.co_firstlineno
        key = (module, function, source_file, line)
        existing = self._function_ids.get(key)
        if existing is not None:
            return existing
        function_id = self._next_function_id
        self._next_function_id += 1
        self._function_ids[key] = function_id
        self._write({
            "event": "function_definition",
            "file": source_file,
            "function": function,
            "function_id": function_id,
            "line": line,
            "module": module,
        })
        return function_id

    def _write(self, event: dict[str, object]) -> None:
        if self._writer is not None:
            self._writer.write(event)


def record_stage_facts(stage: str, **facts: object) -> None:
    """Record allowlisted stage metadata when stage tracing is active."""
    active = _ACTIVE_TRACE.get()
    if active is not None and active.mode == TraceMode.STAGES:
        active.record_stage_facts(stage, facts)
