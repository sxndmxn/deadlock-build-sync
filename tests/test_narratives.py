import json
from dataclasses import replace
from pathlib import Path

import pytest

from deadlock_build_sync.api import Patch
from deadlock_build_sync.narratives import (
    NARRATIVE_PROMPT_VERSION,
    NARRATIVE_SCHEMA_VERSION,
    NarrativeError,
    apply_narrative,
    load_narrative_catalog,
)
from deadlock_build_sync.purchase_guide import GuideCategory, GuideItem, PurchaseGuide

SNAPSHOT_ID = "1" * 64
POLICY_ID = "2" * 64
CONTEXT_ID = "3" * 64
BASIS_ID = "4" * 64
SOURCE_ID = "5" * 64
PATCH = Patch("Patch", 123, "2026-01-01T00:00:00Z")
DESCRIPTION = (
    "Control committed fights with Kelvin's space denial while the supported "
    "CORE path keeps steady pressure available between protective rotations."
)


def guide() -> PurchaseGuide:
    core = GuideItem(101, "Frost Core", 1, 100, 0.5, 0.4, 1.0, ())
    option = GuideItem(102, "Barrier", 1, 80, 0.5, 0.4, 0.8, ())
    return PurchaseGuide(
        12,
        "Kelvin",
        "hero_kelvin",
        {1: (core, option), 2: (), 3: (), 4: ()},
        categories=(
            GuideCategory("CORE ITEMS", (core,), "fixed core text"),
            GuideCategory("TIER 1", (option,), "fixed tier text", optional=True),
        ),
        snapshot_id=SNAPSHOT_ID,
        policy_id=POLICY_ID,
        client_version=123,
        match_mode="ranked",
    )


def write_catalog(path: Path, **overrides: object) -> None:
    entry = {
        "hero_id": 12,
        "path_id": "default",
        "prompt_version": NARRATIVE_PROMPT_VERSION,
        "snapshot_id": SNAPSHOT_ID,
        "policy_id": POLICY_ID,
        "context_sha256": CONTEXT_ID,
        "narrative_basis_sha256": BASIS_ID,
        "build_description": DESCRIPTION,
    }
    document = {
        "schema_version": NARRATIVE_SCHEMA_VERSION,
        "prompt_version": NARRATIVE_PROMPT_VERSION,
        "source_context_sha256": SOURCE_ID,
        "snapshot_id": SNAPSHOT_ID,
        "patch": PATCH.as_dict(),
        "cohort": {
            "client_version": 123,
            "match_mode": "ranked",
            "game_mode": "normal",
        },
        "requested_hero_ids": [12],
        "exclusions": [],
        "heroes": [entry],
        **overrides,
    }
    path.write_text(json.dumps(document), encoding="utf-8")


def test_applies_only_exact_build_description(tmp_path: Path) -> None:
    path = tmp_path / "narratives.json"
    write_catalog(path)
    source = guide()

    updated = apply_narrative(
        source,
        {
            "context_sha256": CONTEXT_ID,
            "narrative_basis_sha256": BASIS_ID,
        },
        PATCH,
        load_narrative_catalog(path),
    )

    assert updated.summary == DESCRIPTION
    assert updated.tactical_profile is None
    assert updated.categories == source.categories
    assert updated.tiers == source.tiers
    assert (
        updated.categories[0].items[0].annotation
        == source.categories[0].items[0].annotation
    )


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("context_sha256", "8" * 64, "context changed"),
        ("narrative_basis_sha256", "8" * 64, "narrative basis changed"),
    ],
)
def test_rejects_changed_context_or_basis(
    tmp_path: Path,
    field: str,
    value: str,
    error: str,
) -> None:
    path = tmp_path / "narratives.json"
    write_catalog(path)
    context = {
        "context_sha256": CONTEXT_ID,
        "narrative_basis_sha256": BASIS_ID,
        field: value,
    }

    with pytest.raises(NarrativeError, match=error):
        apply_narrative(guide(), context, PATCH, load_narrative_catalog(path))


def test_rejects_other_match_mode(tmp_path: Path) -> None:
    path = tmp_path / "narratives.json"
    write_catalog(path)

    with pytest.raises(NarrativeError, match="match mode"):
        apply_narrative(
            replace(guide(), match_mode="unranked"),
            {"context_sha256": CONTEXT_ID, "narrative_basis_sha256": BASIS_ID},
            PATCH,
            load_narrative_catalog(path),
        )


def test_rejects_missing_build_description(tmp_path: Path) -> None:
    path = tmp_path / "narratives.json"
    write_catalog(path)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["heroes"][0].pop("build_description")
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(NarrativeError, match="incomplete"):
        apply_narrative(
            guide(),
            {"context_sha256": CONTEXT_ID, "narrative_basis_sha256": BASIS_ID},
            PATCH,
            load_narrative_catalog(path),
        )


def test_rejects_incomplete_requested_hero_coverage(tmp_path: Path) -> None:
    path = tmp_path / "narratives.json"
    write_catalog(path, requested_hero_ids=[12, 13])

    with pytest.raises(NarrativeError, match="cover every requested hero"):
        load_narrative_catalog(path)


def test_accepts_structured_exclusion_coverage(tmp_path: Path) -> None:
    path = tmp_path / "narratives.json"
    write_catalog(
        path,
        requested_hero_ids=[12, 13],
        exclusions=[{"hero_id": 13, "reason": "incomplete mechanics"}],
    )

    assert load_narrative_catalog(path).exclusions == {13: "incomplete mechanics"}


def test_rejects_outdated_tactical_prompt(tmp_path: Path) -> None:
    path = tmp_path / "narratives.json"
    write_catalog(path, prompt_version=1)

    with pytest.raises(NarrativeError, match="outdated tactical prompt"):
        load_narrative_catalog(path)
