from __future__ import annotations

from typing import TYPE_CHECKING

from .cache import (
    restore_latest,
)
from .cli_support import (
    _ARTIFACT_WRITE_STAGE,
    _POLICY_FILENAME,
    _build_evidence,
    _generate,
    _location,
    _write_policy_artifact,
    _write_strategy_context,
)
from .tracing import record_stage_facts, render_trace_summary

if TYPE_CHECKING:
    import argparse


def _run_export_context(args: argparse.Namespace) -> int:
    location = _location(args)
    evidence_path, evidence = _build_evidence(args)
    generated = _generate(args, evidence, location.account_id)
    _write_strategy_context(args.output, generated)
    record_stage_facts(_ARTIFACT_WRITE_STAGE, path=args.output)
    policy_output = args.policy_output or args.output.with_name(_POLICY_FILENAME)
    _write_policy_artifact(policy_output, generated)
    record_stage_facts(_ARTIFACT_WRITE_STAGE, path=policy_output)
    print(f"Exported {len(generated.contexts)} hero context(s): {args.output}")
    print(f"Policies: {policy_output}")
    print(f"Build evidence: {evidence_path} ({evidence.artifact_id})")
    print(f"Snapshot: {generated.manifest.snapshot_id}")
    return 0


def _run_restore(args: argparse.Namespace) -> int:
    location = _location(args)
    restored = restore_latest(location)
    print(f"Restored cache backup: {restored}")
    print(f"Cache: {location.cache_path}")
    return 0


def _run_trace_summary(args: argparse.Namespace) -> int:
    print(render_trace_summary(args.path.expanduser(), max_nodes=args.max_nodes))
    return 0
