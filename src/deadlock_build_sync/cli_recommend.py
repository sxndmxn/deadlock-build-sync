from __future__ import annotations

import json
from typing import TYPE_CHECKING

from .api import DeadlockApi
from .artifacts import load_policy_artifact
from .cli_support import (
    _BUILD_EVIDENCE_FILENAME,
    _POLICY_FILENAME,
    _describe_preview_guide,
    _discover_cache_location,
    _generate_requested_guides,
    _load_build_evidence,
    _load_optional_narrative_catalog,
    _record_fresh_evidence,
    _render_preview_guide,
    _resolve_artifact_directory,
)
from .freshness import (
    require_current_build_evidence,
)
from .guide_groups import group_guides
from .recommendation import DecisionState, RecommendationError, recommend
from .recommendation_plan import render_recommendation_markdown
from .tracing import record_stage_facts

if TYPE_CHECKING:
    import argparse


def _run_recommend(args: argparse.Namespace) -> int:
    evidence_path = (
        args.build_evidence.expanduser().resolve()
        if args.build_evidence is not None
        else _resolve_artifact_directory(args.artifacts) / _BUILD_EVIDENCE_FILENAME
    )
    evidence = require_current_build_evidence(
        evidence_path,
        DeadlockApi(args.api_base_url),
    )
    _record_fresh_evidence(evidence_path, evidence)
    state = DecisionState.from_file(args.state.expanduser().resolve())
    policy_path = (
        args.policies.expanduser().resolve()
        if args.policies is not None
        else evidence_path.with_name(_POLICY_FILENAME)
    )
    manifest, policies = load_policy_artifact(policy_path)
    policy_patch = manifest.get("patch")
    compatibility = (
        manifest.get("client_version") == evidence.client_version,
        manifest.get("as_of_timestamp") == evidence.as_of_timestamp,
        str(manifest.get("match_mode") or "").casefold()
        == str(evidence.cohort.get("match_mode") or "").casefold(),
        str(manifest.get("game_mode") or "").casefold()
        == str(evidence.cohort.get("game_mode") or "").casefold(),
        isinstance(policy_patch, dict)
        and policy_patch.get("identity") == evidence.patch.get("identity"),
        manifest.get("epochs") == evidence.epochs.as_dict(),
    )
    if not all(compatibility):
        raise RecommendationError(
            "typed policy sidecar differs from the current build evidence"
        )
    default = evidence.heroes.get(state.hero_id)
    path_id = state.path_id or (default.path_id if default else "default")
    policy = policies.get((state.hero_id, path_id))
    if policy is None:
        raise RecommendationError("decision state hero is absent from typed policies")
    pinned_api = DeadlockApi(
        args.api_base_url,
        client_version=evidence.client_version,
        as_of_timestamp=evidence.as_of_timestamp,
        epochs=evidence.epochs,
    )
    decision = recommend(evidence, policy, state, pinned_api.items())
    if args.format == "markdown":
        print(render_recommendation_markdown(decision))
    else:
        print(json.dumps(decision.as_dict(), indent=2, ensure_ascii=False))
    return 0


def _run_preview(args: argparse.Namespace) -> int:
    location = _discover_cache_location(args)
    evidence_path, evidence = _load_build_evidence(args)
    generated = _generate_requested_guides(
        args,
        evidence,
        location.account_id,
        narrative_catalog=_load_optional_narrative_catalog(args),
    )
    guides = group_guides(generated.guides, generated.guide_groups)
    payload = {
        "account_id": location.account_id,
        "persona": generated.persona,
        "snapshot_manifest": generated.manifest.as_dict(),
        "patch": generated.patch.as_dict(),
        "rank_range": generated.manifest.rank_range,
        "exclusions": [
            {"hero_id": hero_id, "reason": reason}
            for hero_id, reason in generated.exclusions
        ],
        "artifacts": {
            "build_evidence": str(evidence_path),
            "build_evidence_id": evidence.artifact_id,
            "context": None,
            "policy": "inline:policies",
            "narrative": str(args.narratives) if args.narratives else None,
        },
        "policies": [policy.as_dict() for policy in generated.policies],
        "guides": [
            _describe_preview_guide(
                guide,
                generated,
                account_id=location.account_id,
            )
            for guide in guides
        ],
    }
    record_stage_facts(
        "preview.output",
        guide_count=len(generated.guides),
        policy_count=len(generated.policies),
    )
    if args.format == "markdown":
        print(
            "\n".join(
                _render_preview_guide(guide, generated, details=args.details)
                for guide in guides
            )
        )
    else:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0
