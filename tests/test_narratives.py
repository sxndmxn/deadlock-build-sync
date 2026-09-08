import json
from dataclasses import replace
from pathlib import Path

import pytest

from deadlock_build_sync.narratives import (
    NarrativeError,
    apply_narrative,
    deterministic_build_description,
    load_narrative_catalog,
)
from tests.narrative_fixtures import (
    BASIS_ID,
    CONTEXT_ID,
    DESCRIPTION,
    PATCH,
    guide,
    write_catalog,
)


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
    context: dict[str, object] = {
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


def test_rejects_outdated_description_generator(tmp_path: Path) -> None:
    path = tmp_path / "narratives.json"
    write_catalog(path, generator_version=0)

    with pytest.raises(NarrativeError, match="outdated description generator"):
        load_narrative_catalog(path)


def test_build_description_is_deterministic_and_grounded() -> None:
    context: dict[str, object] = {
        "hero": "Kelvin",
        "hero_mechanics": {
            "description": {
                "role": "Protect allies",
                "playstyle": "Controls space with ice.",
            }
        },
        "policy": {"strategic_role": "Control support"},
        "ability_policy": {
            "steps": [
                {"action": "UPGRADE_3", "ability": "Frozen Shelter"},
            ]
        },
        "projection": {"build": {"archetype": "Spirit Damage"}},
    }

    assert deterministic_build_description(context) == (
        "Kelvin: Protect allies. Controls space with ice. Follow the shown Spirit "
        "Damage CORE order and max Frozen Shelter first. Use conditional cards only "
        "when their VS line applies; all optional rows stay outside Queue."
    )


@pytest.mark.parametrize(
    "archetype",
    ["Weapon", "Spirit", "Vitality", "Hybrid", "Support"],
)
def test_build_description_preserves_the_selected_archetype(archetype: str) -> None:
    context: dict[str, object] = {
        "hero": "Test Hero",
        "hero_mechanics": {
            "description": {
                "role": "Control the fight",
                "playstyle": "Protect the team.",
            }
        },
        "ability_policy": {
            "steps": [{"action": "UPGRADE_3", "ability": "Test Ability"}]
        },
        "projection": {"build": {"archetype": archetype}},
    }

    description = deterministic_build_description(context)

    assert f"shown {archetype} CORE order" in description
