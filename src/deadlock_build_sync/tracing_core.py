from __future__ import annotations

import json
import os
import re
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

if TYPE_CHECKING:
    from types import FrameType

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
    "deadlock_build_sync.service_generation.generate_guides": "guide.generation",
    "deadlock_build_sync.service_policy._build_policy": "policy",
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

    def write(self, event: dict[str, object]) -> None:
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


def _project_module(frame: FrameType) -> str | None:
    module = frame.f_globals.get("__name__")
    if not isinstance(module, str):
        return None
    if module.startswith("deadlock_build_sync.tracing") or not (
        module == "deadlock_build_sync" or module.startswith("deadlock_build_sync.")
    ):
        return None
    return module


def _module_file(module: str, frame: FrameType) -> str:
    suffix = Path(frame.f_code.co_filename).suffix or ".py"
    return module.replace(".", "/") + suffix


def _exception_name(exception_type: object) -> str:
    module = getattr(exception_type, "__module__", "builtins")
    name = getattr(exception_type, "__qualname__", "Exception")
    return f"{module}.{name}"


def _normalize_stage_fact(key: str, value: object) -> object:
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
