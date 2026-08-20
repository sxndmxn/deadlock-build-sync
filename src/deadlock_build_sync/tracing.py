from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self, TextIO

if TYPE_CHECKING:
    from types import FrameType, TracebackType

TRACE_ENVIRONMENT_VARIABLE = "DEADLOCK_BUILD_SYNC_TRACE"
TRACE_FILE_NAME = "trace.jsonl"
TRACE_SCHEMA_VERSION = 1
DEFAULT_CALL_TRACE_MAX_BYTES = 100 * 1024 * 1024
TRACE_RETENTION_RUNS = 3
_TRACE_DIRECTORY_PATTERN = re.compile(r"^\d{8}T\d{6}\.\d{6}Z-\d+(?:-\d+)?$")
_ACTIVE_MARKER_NAME = ".active"


class TraceError(ValueError):
    """Raised when an execution trace cannot be configured or summarized."""


class TraceMode(StrEnum):
    """Supported execution-trace detail levels."""

    STAGES = "stages"
    CALLS = "calls"

    @classmethod
    def parse(cls, value: str) -> TraceMode:
        try:
            return cls(value.strip().casefold())
        except ValueError as error:
            choices = ", ".join(mode.value for mode in cls)
            raise TraceError(f"trace mode must be one of: {choices}") from error


# These are stable pipeline boundaries, not every internal operation in a stage.
_STAGE_BOUNDARIES = {
    "deadlock_build_sync.cli._dispatch": "command",
    "deadlock_build_sync.build_evidence.load_build_evidence": "evidence.admission",
    "deadlock_build_sync.freshness.require_current_build_evidence": (
        "evidence.freshness"
    ),
    "deadlock_build_sync.freshness.build_freshness_report": "status",
    "deadlock_build_sync.service.generate_guides": "guide.generation",
    "deadlock_build_sync.service._build_policy": "policy",
    "deadlock_build_sync.renderer.project_policy_to_guide": "projection",
    "deadlock_build_sync.strategy_context.build_hero_strategy_context": (
        "context.export"
    ),
    "deadlock_build_sync.narratives.apply_narrative": "narrative.admission",
    "deadlock_build_sync.presentation.build_presentation": "presentation",
    "deadlock_build_sync.protobuf.describe_guide": "preview.description",
    "deadlock_build_sync.protobuf.encode_hero_build": "protobuf.serialization",
    "deadlock_build_sync.artifacts.atomic_write_json": "artifact.write",
    "deadlock_build_sync.cache.install_guides": "steam.install",
    "deadlock_build_sync.cache.update_managed_builds": "steam.projection",
    "deadlock_build_sync.cache._create_backup": "steam.backup",
    "deadlock_build_sync.cache._atomic_replace": "steam.replace",
    "deadlock_build_sync.recommendation.recommend": "recommendation",
}

_SAFE_STAGE_FACTS = frozenset({
    "artifact_id",
    "context_count",
    "created",
    "exit_code",
    "guide_count",
    "hero_count",
    "path",
    "policy_count",
    "removed",
    "row_count",
    "skipped_count",
    "snapshot_id",
    "updated",
})
_LONG_NUMERIC_TOKEN = re.compile(r"\d{6,}")


def state_directory() -> Path:
    """Return the application state directory without creating it.

    Returns:
        The XDG-compatible application state directory.

    """
    configured = os.environ.get("XDG_STATE_HOME")
    root = Path(configured).expanduser() if configured else Path.home() / ".local/state"
    return root / "deadlock-build-sync"


def _is_inactive_trace_directory(path: Path) -> bool:
    eligible = not (
        path.is_symlink()
        or not _TRACE_DIRECTORY_PATTERN.fullmatch(path.name)
        or not path.is_dir()
    )
    if not eligible:
        return False
    trace_path = path / TRACE_FILE_NAME
    inactive = not trace_path.is_symlink() and trace_path.is_file()
    marker = path / _ACTIVE_MARKER_NAME
    if inactive and marker.exists():
        inactive = False
        try:
            process_id = int(marker.read_text(encoding="ascii"))
        except (OSError, ValueError):
            process_id = 0
        if process_id > 0:
            try:
                os.kill(process_id, 0)
            except ProcessLookupError:
                inactive = True
            except PermissionError:
                pass
    return inactive


class _JsonLinesWriter:
    def __init__(self, path: Path, *, max_bytes: int) -> None:
        if max_bytes <= 0:
            raise TraceError("trace byte limit must be positive")
        self.path = path
        self.max_bytes = max_bytes
        self.bytes_written = 0
        self.truncated = False
        self.failed = False
        self._output: TextIO = path.open("x", encoding="utf-8", buffering=1)

    def write(self, event: dict[str, Any]) -> None:
        if self.truncated or self.failed:
            return
        line = (
            json.dumps(
                event,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        )
        encoded_size = len(line.encode("utf-8"))
        truncation_line = self._truncation_line()
        reserved_size = len(truncation_line.encode("utf-8"))
        if self.bytes_written + encoded_size + reserved_size > self.max_bytes:
            self._truncate()
            return
        try:
            self._output.write(line)
        except OSError:
            self.failed = True
            return
        self.bytes_written += encoded_size

    def _truncate(self) -> None:
        line = self._truncation_line()
        encoded_size = len(line.encode("utf-8"))
        if self.bytes_written + encoded_size <= self.max_bytes:
            try:
                self._output.write(line)
            except OSError:
                self.failed = True
            else:
                self.bytes_written += encoded_size
        self.truncated = True

    def _truncation_line(self) -> str:
        event = {
            "event": "trace_truncated",
            "max_bytes": self.max_bytes,
            "schema_version": TRACE_SCHEMA_VERSION,
        }
        return json.dumps(event, separators=(",", ":"), sort_keys=True) + "\n"

    def close(self) -> None:
        try:
            self._output.close()
        except OSError:
            self.failed = True


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
        self._previous_profile: Any = None
        self._previous_trace: Any = None
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
        self._previous_profile = sys.getprofile()
        self._previous_trace = sys.gettrace()
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
        event: dict[str, Any] = {
            "elapsed_ns": elapsed_ns,
            "event": "trace_complete",
            "exit_code": self._exit_code,
            "schema_version": TRACE_SCHEMA_VERSION,
            "status": "failure" if failed else "success",
        }
        if exception_type is not None:
            event["exception_type"] = _exception_name(exception_type)
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

    @property
    def write_failed(self) -> bool:
        return self._writer.failed if self._writer is not None else False

    def record_stage_facts(self, stage: str, facts: dict[str, Any]) -> None:
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

    def _profile(self, frame: FrameType, event: str, _argument: Any) -> None:
        if event == "call":
            self._record_call(frame)
        elif event == "return":
            self._record_return(frame)

    def _trace_exceptions(
        self,
        frame: FrameType,
        event: str,
        argument: Any,
    ) -> Any:
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
            exception_type = argument[0]
            active.exception_pending = True
            active.exception_type = _exception_name(exception_type)
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
            event: dict[str, Any] = {
                "call_id": active.span_id,
                "elapsed_ns": elapsed_ns,
                "event": "return",
                "status": status,
            }
            if active.exception_type is not None:
                event["exception_type"] = active.exception_type
            self._write(event)
        else:
            event = {
                "elapsed_ns": elapsed_ns,
                "event": "stage_end",
                "schema_version": TRACE_SCHEMA_VERSION,
                "stage": active.stage,
                "stage_id": active.span_id,
                "status": status,
            }
            if active.exception_type is not None:
                event["exception_type"] = active.exception_type
            self._write(event)

    def _project_parent(self, frame: FrameType) -> _ActiveSpan | None:
        parent = frame.f_back
        while parent is not None:
            active = self._spans.get(id(parent))
            if active is not None:
                return active
            parent = parent.f_back
        return None

    def _function_id(self, module: str, function: str, frame: FrameType) -> int:
        source_file = _module_file(module, frame)
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

    def _write(self, event: dict[str, Any]) -> None:
        if self._writer is not None:
            self._writer.write(event)


def record_stage_facts(stage: str, **facts: Any) -> None:
    """Record allowlisted stage metadata when stage tracing is active."""
    active = _ACTIVE_TRACE.get()
    if active is not None and active.mode == TraceMode.STAGES:
        active.record_stage_facts(stage, facts)


def _project_module(frame: FrameType) -> str | None:
    module = frame.f_globals.get("__name__")
    if not isinstance(module, str):
        return None
    if module == "deadlock_build_sync.tracing" or not (
        module == "deadlock_build_sync" or module.startswith("deadlock_build_sync.")
    ):
        return None
    return module


def _module_file(module: str, frame: FrameType) -> str:
    suffix = Path(frame.f_code.co_filename).suffix or ".py"
    return module.replace(".", "/") + suffix


def _exception_name(exception_type: Any) -> str:
    module = getattr(exception_type, "__module__", "builtins")
    name = getattr(exception_type, "__qualname__", "Exception")
    return f"{module}.{name}"


def _normalize_stage_fact(key: str, value: Any) -> Any:
    if key == "path" and isinstance(value, (Path, str)):
        return _sanitize_path(value)
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, Path):
        return str(value)
    raise TraceError("stage trace facts must be paths, strings, integers, or booleans")


def _sanitize_path(value: Path | str) -> str:
    components = (
        "<numeric-id>" if component.isdigit() else component
        for component in str(value).split("/")
    )
    return _LONG_NUMERIC_TOKEN.sub("<numeric-id>", "/".join(components))


@dataclass
class _SummarySpan:
    span_id: int
    parent_id: int | None
    depth: int
    label: str
    elapsed_ns: int | None = None
    status: str | None = None


def _record_function_definition(
    event: dict[str, Any],
    line_number: int,
    functions: dict[int, str],
) -> None:
    identifier = event.get("function_id")
    module = event.get("module")
    function = event.get("function")
    if (
        not isinstance(identifier, int)
        or not isinstance(module, str)
        or not isinstance(function, str)
    ):
        raise TraceError(f"trace line {line_number} has an invalid function definition")
    functions[identifier] = f"{module}.{function}"


def _record_terminal_event(
    event: dict[str, Any],
    spans: dict[int, _SummarySpan],
) -> None:
    identifier = event.get("call_id", event.get("stage_id"))
    if not isinstance(identifier, int) or identifier not in spans:
        return
    elapsed_ns = event.get("elapsed_ns")
    status = event.get("status")
    if isinstance(elapsed_ns, int):
        spans[identifier].elapsed_ns = elapsed_ns
    if isinstance(status, str):
        spans[identifier].status = status


@dataclass
class _TraceSummaryData:
    metadata: dict[str, Any] = field(default_factory=dict)
    functions: dict[int, str] = field(default_factory=dict)
    spans: dict[int, _SummarySpan] = field(default_factory=dict)
    order: list[int] = field(default_factory=list)
    truncated: bool = False

    def record(self, event: dict[str, Any], line_number: int) -> None:
        kind = event.get("event")
        if kind == "trace_start":
            self.metadata.update(event)
        elif kind == "function_definition":
            _record_function_definition(event, line_number, self.functions)
        elif kind == "call":
            span = _call_summary_span(event, line_number, self.functions, self.spans)
            self.spans[span.span_id] = span
            self.order.append(span.span_id)
        elif kind == "stage_start":
            span = _stage_summary_span(event, line_number)
            self.spans[span.span_id] = span
            self.order.append(span.span_id)
        elif kind in {"return", "stage_end"}:
            _record_terminal_event(event, self.spans)
        elif kind == "trace_complete":
            self.metadata["status"] = event.get("status")
            self.metadata["elapsed_ns"] = event.get("elapsed_ns")
        elif kind == "trace_truncated":
            self.truncated = True


def _read_trace_summary(trace_path: Path) -> _TraceSummaryData:
    summary = _TraceSummaryData()
    with trace_path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError as error:
                raise TraceError(
                    f"trace line {line_number} is not valid JSON"
                ) from error
            if not isinstance(event, dict):
                raise TraceError(f"trace line {line_number} is not a JSON object")
            summary.record(event, line_number)
    return summary


def _trace_tree_lines(
    trace_path: Path,
    summary: _TraceSummaryData,
    max_nodes: int,
) -> list[str]:
    mode = summary.metadata.get("mode", "unknown")
    command = summary.metadata.get("command", "unknown")
    status = summary.metadata.get("status", "incomplete")
    elapsed_ns = summary.metadata.get("elapsed_ns")
    elapsed = _format_duration(elapsed_ns if isinstance(elapsed_ns, int) else None)
    tree_label = "Call tree" if mode == TraceMode.CALLS else "Stage tree"
    lines = [
        f"Trace: {trace_path}",
        f"Mode: {mode} | Command: {command} | Status: {status} | Elapsed: {elapsed}",
        f"{tree_label}:",
    ]
    for identifier in summary.order[:max_nodes]:
        span = summary.spans[identifier]
        terminal = span.status or "incomplete"
        lines.append(
            f"{'  ' * span.depth}{span.label} "
            f"[{_format_duration(span.elapsed_ns)}, {terminal}]"
        )
    omitted = len(summary.order) - max_nodes
    if omitted > 0:
        lines.append(f"... {omitted} additional span(s) omitted")
    if summary.truncated:
        lines.append("Trace file reached its size limit; later events are unavailable.")
    return lines


def _inclusive_time_lines(spans: dict[int, _SummarySpan]) -> list[str]:
    totals: dict[str, tuple[int, int, int]] = {}
    for span in spans.values():
        calls, total_ns, maximum_ns = totals.get(span.label, (0, 0, 0))
        duration = span.elapsed_ns or 0
        totals[span.label] = (
            calls + 1,
            total_ns + duration,
            max(maximum_ns, duration),
        )
    lines = ["Per-function inclusive time:"]
    for label, (calls, total_ns, maximum_ns) in sorted(
        totals.items(), key=lambda item: (-item[1][1], item[0])
    ):
        lines.append(
            f"{_format_duration(total_ns):>10} total | "
            f"{_format_duration(maximum_ns):>10} max | {calls:>5} call(s) | {label}"
        )
    return lines


def render_trace_summary(path: Path, *, max_nodes: int = 200) -> str:
    """Render a bounded call/stage tree and inclusive elapsed-time totals.

    Returns:
        A plain-text summary suitable for terminal output.

    Raises:
        TraceError: If the trace is missing, malformed, or the limit is invalid.

    """
    if max_nodes <= 0:
        raise TraceError("trace summary node limit must be positive")
    trace_path = path / TRACE_FILE_NAME if path.is_dir() else path
    if not trace_path.is_file():
        raise TraceError(f"trace does not exist: {trace_path}")
    summary = _read_trace_summary(trace_path)
    lines = _trace_tree_lines(trace_path, summary, max_nodes)
    lines.extend(_inclusive_time_lines(summary.spans))
    return "\n".join(lines)


def _call_summary_span(
    event: dict[str, Any],
    line_number: int,
    functions: dict[int, str],
    spans: dict[int, _SummarySpan],
) -> _SummarySpan:
    identifier = event.get("call_id")
    function_id = event.get("function_id")
    module = event.get("module")
    function = event.get("function")
    if not isinstance(identifier, int):
        raise TraceError(f"trace line {line_number} has an invalid call event")
    if isinstance(function_id, int):
        label = functions.get(function_id)
        if label is None:
            raise TraceError(f"trace line {line_number} references an unknown function")
    elif isinstance(module, str) and isinstance(function, str):
        # Schema v1 traces written before function interning remain readable.
        label = f"{module}.{function}"
    else:
        raise TraceError(f"trace line {line_number} has an invalid call event")
    parent = event.get("parent_call_id")
    depth = event.get("depth")
    if not isinstance(depth, int):
        parent_span = spans.get(parent) if isinstance(parent, int) else None
        depth = parent_span.depth + 1 if parent_span is not None else 0
    return _SummarySpan(
        span_id=identifier,
        parent_id=parent if isinstance(parent, int) else None,
        depth=depth,
        label=label,
    )


def _stage_summary_span(event: dict[str, Any], line_number: int) -> _SummarySpan:
    identifier = event.get("stage_id")
    stage = event.get("stage")
    if not isinstance(identifier, int) or not isinstance(stage, str):
        raise TraceError(f"trace line {line_number} has an invalid stage event")
    parent = event.get("parent_stage_id")
    depth = event.get("depth")
    return _SummarySpan(
        span_id=identifier,
        parent_id=parent if isinstance(parent, int) else None,
        depth=depth if isinstance(depth, int) else 0,
        label=stage,
    )


def _format_duration(elapsed_ns: int | None) -> str:
    if elapsed_ns is None:
        return "incomplete"
    if elapsed_ns < 1_000:
        return f"{elapsed_ns}ns"
    if elapsed_ns < 1_000_000:
        return f"{elapsed_ns / 1_000:.3f}us"
    if elapsed_ns < 1_000_000_000:
        return f"{elapsed_ns / 1_000_000:.3f}ms"
    return f"{elapsed_ns / 1_000_000_000:.3f}s"
