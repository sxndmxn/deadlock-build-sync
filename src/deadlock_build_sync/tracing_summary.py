from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .tracing_core import (
    TRACE_FILE_NAME,
    TraceError,
    TraceMode,
)

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class _SummarySpan:
    span_id: int
    parent_id: int | None
    depth: int
    label: str
    elapsed_ns: int | None = None
    status: str | None = None


def _record_function_definition(
    event: dict[str, object],
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
    event: dict[str, object],
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
    metadata: dict[str, object] = field(default_factory=dict)
    functions: dict[int, str] = field(default_factory=dict)
    spans: dict[int, _SummarySpan] = field(default_factory=dict)
    order: list[int] = field(default_factory=list)
    truncated: bool = False

    def record(self, event: dict[str, object], line_number: int) -> None:
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
    event: dict[str, object],
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


def _stage_summary_span(event: dict[str, object], line_number: int) -> _SummarySpan:
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
