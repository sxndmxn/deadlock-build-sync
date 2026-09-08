import json
from dataclasses import asdict
from datetime import UTC, datetime, tzinfo
from pathlib import Path

import pytest

import tests.artifact_bundle_fixtures as bundle_fixtures
from deadlock_build_sync.artifact_bundle import load_artifact_guide_bundle
from deadlock_build_sync.snapshot import (
    sha256_json,
)
from deadlock_build_sync.strategy_context import (
    calculate_context_sha256,
    calculate_narrative_basis_sha256,
    calculate_source_context_sha256,
)
from tests.artifact_bundle_fixtures import (
    _write_bundle,
)
from tests.serialization_fixtures import json_default


def test_loads_exact_reviewed_bundle_without_analytics_refetch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_at = datetime(2026, 1, 2, tzinfo=UTC)

    class FixedDatetime:
        @staticmethod
        def now(_timezone: object) -> datetime:
            return created_at

        @staticmethod
        def fromtimestamp(timestamp: float, timezone: tzinfo) -> datetime:
            return datetime.fromtimestamp(timestamp, timezone)

    monkeypatch.setattr(bundle_fixtures, "datetime", FixedDatetime)
    context_path, policy_path, narrative_path, evidence_path = _write_bundle(tmp_path)

    bundle = load_artifact_guide_bundle(
        context_path,
        policy_path,
        narrative_path,
        evidence_path,
    )

    normalized = json.loads(json.dumps(asdict(bundle), default=json_default))
    assert sha256_json(normalized) == (
        "de80951a48a38f25041bf77b3f7b67f1ad7617235ab02dce1ee0616415c1ac61"
    )
    assert len(bundle.guides) == 1
    guide = bundle.guides[0]
    assert guide.hero_name == "Kelvin"
    queue = [
        item.item_id
        for row in guide.rendered_categories
        if not row.optional
        for item in row.items
    ]
    assert queue == list(range(1001, 1007))
    assert [len(row.items) for row in guide.rendered_categories[-4:]] == [10] * 4
    assert all(row.optional for row in guide.rendered_categories[-4:])
    assert guide.summary == (
        "Control committed fights around allied pressure while the reviewed CORE "
        "path keeps reliable damage available."
    )
    assert "souls" in guide.rendered_categories[0].items[0].annotation
    assert all(
        len(item.annotation.splitlines()) == 3
        for row in guide.rendered_categories
        for item in row.items
    )
    assert guide.ability_path is not None
    assert len(guide.ability_path.ability_ids) == 16
    assert guide.build_tag_ids == (10, 1005, 3)
    assert guide.build_tag_labels == ("Ability 10", "Item 1005", "Damage")


def test_rejects_edited_projection_even_when_other_artifacts_are_unchanged(
    tmp_path: Path,
) -> None:
    context_path, policy_path, narrative_path, evidence_path = _write_bundle(tmp_path)
    context = json.loads(context_path.read_text(encoding="utf-8"))
    context["heroes"][0]["projection"]["categories"][0]["items"][0]["item_id"] = 999
    context_path.write_text(json.dumps(context), encoding="utf-8")

    with pytest.raises(ValueError, match="edited"):
        load_artifact_guide_bundle(
            context_path,
            policy_path,
            narrative_path,
            evidence_path,
        )


@pytest.mark.parametrize(
    "change",
    [
        "dimensions",
        "schema",
        "cohort",
        "missing row",
        "duplicate item",
        "wrong item",
        "annotation",
        "optional flag",
        "row order",
        "item field",
    ],
)
def test_rejects_projection_with_stale_canonical_contract(
    tmp_path: Path, change: str
) -> None:
    context_path, policy_path, narrative_path, evidence_path = _write_bundle(tmp_path)
    context = json.loads(context_path.read_text(encoding="utf-8"))
    hero = context["heroes"][0]
    if change == "dimensions":
        hero["projection"]["categories"][0]["height"] = 999.0
    elif change == "schema":
        hero["projection"]["guide_version"] = 2
    elif change == "cohort":
        hero["purchase_guidance"]["cohort"]["minimum_badge"] = 61
    else:
        categories = hero["projection"]["categories"]
        row = categories[0]
        if change == "missing row":
            categories.pop()
        elif change == "duplicate item":
            row["items"].append(row["items"][0])
        elif change == "wrong item":
            row["items"][0]["item_id"] = 999
        elif change == "annotation":
            row["items"][0]["annotation"] = "stale text"
        elif change == "optional flag":
            row["optional"] = True
        elif change == "row order":
            categories[0], categories[1] = categories[1], categories[0]
        else:
            row["items"][0]["required_flex_slots"] = True
    hero["narrative_basis_sha256"] = calculate_narrative_basis_sha256(hero)
    hero["context_sha256"] = calculate_context_sha256(hero)
    context["source_context_sha256"] = calculate_source_context_sha256(context)
    context_path.write_text(json.dumps(context), encoding="utf-8")

    narratives = json.loads(narrative_path.read_text(encoding="utf-8"))
    narratives["source_context_sha256"] = context["source_context_sha256"]
    narratives["heroes"][0]["context_sha256"] = hero["context_sha256"]
    narratives["heroes"][0]["narrative_basis_sha256"] = hero["narrative_basis_sha256"]
    narrative_path.write_text(json.dumps(narratives), encoding="utf-8")

    with pytest.raises(ValueError, match=r"canonical purchase guide.*refresh-evidence"):
        load_artifact_guide_bundle(
            context_path,
            policy_path,
            narrative_path,
            evidence_path,
        )


def test_rejects_crossed_policy_snapshot(tmp_path: Path) -> None:
    context_path, policy_path, narrative_path, evidence_path = _write_bundle(tmp_path)
    policies = json.loads(policy_path.read_text(encoding="utf-8"))
    policies["snapshot_manifest"]["created_at"] = "2026-02-01T00:00:00Z"
    policy_path.write_text(json.dumps(policies), encoding="utf-8")

    with pytest.raises(ValueError, match="manifests differ"):
        load_artifact_guide_bundle(
            context_path,
            policy_path,
            narrative_path,
            evidence_path,
        )


def test_rejects_build_evidence_outside_the_reviewed_snapshot(tmp_path: Path) -> None:
    context_path, policy_path, narrative_path, evidence_path = _write_bundle(tmp_path)
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["producer"] = "other-fixture"
    payload = {key: value for key, value in evidence.items() if key != "artifact_id"}
    evidence["artifact_id"] = sha256_json(payload)
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")

    with pytest.raises(ValueError, match="differs from the artifact snapshot"):
        load_artifact_guide_bundle(
            context_path,
            policy_path,
            narrative_path,
            evidence_path,
        )
