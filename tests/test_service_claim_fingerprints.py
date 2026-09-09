from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from deadlock_build_sync import service_claims, snapshot
from deadlock_build_sync.mechanics import AbilityDefinition
from tests.cache_fixtures import make_complete_guide
from tests.test_snapshot import manifest as make_snapshot_manifest

if TYPE_CHECKING:
    import pytest


def test_claims_share_one_calculation_and_recheck_changed_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guide = make_complete_guide()
    tiers = {
        tier: tuple(
            replace(
                item,
                eligible_player_matches=100,
                adopter_matches=60,
                purchase_adoption=0.6,
            )
            for item in items
        )
        for tier, items in guide.tiers.items()
    }
    guide = replace(guide, tiers=tiers, core_items=tiers[1], backbone_items=tiers[1])
    manifest = make_snapshot_manifest(
        created_at="2026-09-09T00:00:00Z", fetched_at="2026-09-09T00:00:00Z"
    )
    expected = manifest.snapshot_id
    calculate = snapshot.sha256_json
    calculations: list[str] = []

    def calculate_fingerprint(value: object) -> str:
        fingerprint = calculate(value)
        calculations.append(fingerprint)
        return fingerprint

    monkeypatch.setattr(snapshot, "sha256_json", calculate_fingerprint)
    definitions = {10: AbilityDefinition(10, 1), 20: AbilityDefinition(20, 2)}
    evidence, core = service_claims._build_policy_evidence(guide, definitions, manifest)
    assert len(evidence) == 35
    assert calculations == [expected]
    assert {claim.snapshot_id for claim in evidence.values()} == {expected}
    assert core.snapshot_id == expected

    manifest.records[0].parameters["version"] = 124
    changed, changed_core = service_claims._build_policy_evidence(
        guide, definitions, manifest
    )
    assert len(calculations) == 2
    assert calculations[-1] != expected
    assert changed.keys() == evidence.keys()
    assert {claim.snapshot_id for claim in changed.values()} == {calculations[-1]}
    assert changed_core.snapshot_id == calculations[-1]
