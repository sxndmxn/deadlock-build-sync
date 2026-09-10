from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from deadlock_build_sync import freshness
from deadlock_build_sync.freshness import FreshnessStage, FreshnessState
from deadlock_build_sync.guide_groups import group_guides
from deadlock_build_sync.service import generate_guides
from tests.service_evidence_fixtures import make_grouped_build_evidence
from tests.service_fake_api import FakeApi, make_ability_rows, make_duration_statistics

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("damage", ["none", "missing", "extra", "snapshot", "policy"])
@pytest.mark.parametrize("group_id", ["", "default"])
def test_status_compares_installed_groups_with_their_default_policies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str, group_id: str
) -> None:
    api = FakeApi(
        ability_rows=make_ability_rows(), duration_points=make_duration_statistics()
    )
    evidence = make_grouped_build_evidence(api)
    default, variant = evidence.hero_builds[12]
    evidence = replace(
        evidence,
        hero_builds={12: (replace(default, guide_group_id=group_id), variant)},
    )
    generated = generate_guides(
        api,
        build_evidence=evidence,
        account_id=34,
        hero_query="Kelvin",
        all_heroes=False,
    )
    guides = group_guides(generated.guides, generated.guide_groups)
    assert len(generated.contexts) == 2
    assert len(guides) == 1
    context: dict[str, object] = {
        "snapshot_manifest": generated.manifest.as_dict(),
        "heroes": generated.contexts,
    }
    installed = {
        (guide.hero_id, guide.path_id): (
            f"Snapshot: {generated.manifest.snapshot_id}. Policy: {guide.policy_id}."
        )
        for guide in guides
    }
    key = guides[0].hero_id, guides[0].path_id
    if damage == "missing":
        installed.clear()
    elif damage == "extra":
        installed[12, "alternative"] = installed[key]
    elif damage in {"snapshot", "policy"}:
        installed[key] = installed[key].replace(
            generated.manifest.snapshot_id
            if damage == "snapshot"
            else guides[0].policy_id,
            "incorrect",
        )
    current = FreshnessStage("fixture", FreshnessState.CURRENT, "validated")
    monkeypatch.setattr(
        freshness, "_check_evidence_freshness", lambda *_args: (current, evidence)
    )
    monkeypatch.setattr(
        freshness, "_check_context_freshness", lambda *_args: (current, context)
    )
    for function in (
        "_check_policy_freshness",
        "_check_narrative_freshness",
        "_check_bundle_freshness",
    ):
        monkeypatch.setattr(freshness, function, lambda *_args: current)
    monkeypatch.setattr(
        freshness, "_read_installed_descriptions", lambda *_args: installed
    )
    report = freshness.build_freshness_report(
        tmp_path, api, cache_path=tmp_path / "cache", account_id=34
    )
    expected = FreshnessState.CURRENT if damage == "none" else FreshnessState.STALE
    assert report.stages[-1].state is expected
    assert report.exit_code == (0 if damage == "none" else 2)
