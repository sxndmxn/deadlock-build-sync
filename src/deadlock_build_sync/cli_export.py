from __future__ import annotations

from typing import TYPE_CHECKING

from .artifacts import atomic_write_json
from .cache import (
    restore_latest,
)
from .cli_support import (
    _ARTIFACT_WRITE_STAGE,
    _POLICY_FILENAME,
    _api,
    _build_evidence,
    _location,
    _record_generated_facts,
    _report_skipped,
    _requested_hero_ids,
    _write_policy_artifact,
)
from .service import generate_guides
from .strategy_context import build_strategy_context_document
from .tracing import record_stage_facts, render_trace_summary

if TYPE_CHECKING:
    import argparse


def _run_export_context(args: argparse.Namespace) -> int:
    location = _location(args)
    evidence_path, evidence = _build_evidence(args)
    generated = generate_guides(
        _api(args, evidence),
        build_evidence=evidence,
        account_id=location.account_id,
        hero_query=args.hero,
        all_heroes=args.all,
    )
    _record_generated_facts(generated)
    _report_skipped(generated)
    document = build_strategy_context_document(
        generated.patch,
        generated.contexts,
        manifest=generated.manifest,
        item_mechanics=generated.item_mechanics,
        requested_hero_ids=_requested_hero_ids(generated),
        exclusions=generated.exclusions,
    )
    atomic_write_json(args.output, document, compact=True)
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
