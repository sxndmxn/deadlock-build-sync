"""Read-only build-quality report and prospective replay entry point."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from .build_evidence import reliable_purchase_window
from .cli_support import _resolve_artifact_directory
from .quality import evaluate_policy
from .quality_inputs import load_quality_inputs, load_replay_assets
from .quality_replay import parse_replay
from .recommendation_state import RecommendationError
from .snapshot import sha256_json

if TYPE_CHECKING:
    import argparse

    from .quality_inputs import QualityInputs
    from .quality_replay import ReplayCase


def build_quality_report(
    inputs: QualityInputs,
    cases: tuple[ReplayCase, ...],
    assets: list[dict[str, object]],
    replay_sha256: str | None,
) -> dict[str, object]:
    builds = []
    for policy in inputs.policies:
        evidence = next(
            build
            for build in inputs.evidence.hero_builds.get(
                policy.hero_id, (inputs.evidence.heroes[policy.hero_id],)
            )
            if build.path_id == policy.path_id
        )
        ability = inputs.abilities[policy.policy_id].quality_assessment()
        replay = evaluate_policy(inputs.evidence, policy, evidence, cases, assets)
        builds.append({
            "hero_id": policy.hero_id,
            "path_id": policy.path_id,
            "policy_id": policy.policy_id,
            "snapshot_id": policy.snapshot_id,
            "status": (
                "fail"
                if "fail" in {ability["status"], replay["status"]}
                else "pass"
                if ability["status"] == replay["status"] == "pass"
                else "unevaluated"
            ),
            "reason": "status covers support, compatibility and route replay; not outcome superiority",
            "ability": ability,
            "replay": replay,
            "core_support_by_fold": evidence.core_policy.default_fold_matches,
            "purchase_windows": {
                "supported_items": sum(
                    reliable_purchase_window(item) is not None
                    for item in evidence.items
                ),
                "items": len(evidence.items),
            },
        })
    payload = {
        "schema_version": 1,
        "build_evidence_id": inputs.evidence.artifact_id,
        "context_sha256": inputs.context_sha256,
        "replay_sha256": replay_sha256,
        "frozen_cutoff": inputs.cutoff,
        "cohort": inputs.evidence.cohort,
        "patch": inputs.evidence.patch,
        "client_version": inputs.evidence.client_version,
        "status": (
            "fail"
            if any(build["status"] == "fail" for build in builds)
            else "pass"
            if builds and all(build["status"] == "pass" for build in builds)
            else "unevaluated"
        ),
        "builds": builds,
        "claim": "No build is certified to improve match outcomes by this report.",
    }
    return {**payload, "report_id": sha256_json(payload)}


def run_quality_report(args: argparse.Namespace) -> int:
    inputs = load_quality_inputs(_resolve_artifact_directory(args.artifacts))
    cases: tuple[ReplayCase, ...] = ()
    assets: list[dict[str, object]] = []
    replay_hash = None
    if args.replay is not None:
        if args.assets is None:
            raise RecommendationError(
                "quality replay requires --assets with pinned item assets"
            )
        document = json.loads(args.replay.read_bytes())
        cases = parse_replay(
            document,
            inputs.policies,
            cutoff=inputs.cutoff,
            evidence_id=inputs.evidence.artifact_id,
        )
        assets = load_replay_assets(args.assets, inputs.evidence)
        replay_hash = sha256_json(document)
    report = build_quality_report(inputs, cases, assets, replay_hash)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return {"fail": 1, "unevaluated": 2, "pass": 0}[str(report["status"])]
