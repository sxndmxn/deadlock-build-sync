import copy
from typing import Any

import pytest

from deadlock_build_sync.narratives import NARRATIVE_GENERATOR_VERSION
from scripts import generate_narratives


def packet() -> dict[str, Any]:
    return {
        "hero_id": 12,
        "path_id": "default",
        "path_label": "Weapon Damage",
        "hero": "Kelvin",
        "snapshot_id": "1" * 64,
        "policy_id": "2" * 64,
        "context_sha256": "3" * 64,
        "narrative_basis_sha256": "5" * 64,
        "hero_mechanics": {
            "description": {
                "role": "Protect allies",
                "playstyle": "Control space with ice and protect the team.",
            }
        },
        "ability_policy": {
            "steps": [
                {"action": "UPGRADE_3", "ability": "Frozen Shelter"},
            ]
        },
        "policy": {"strategic_role": "control support"},
        "projection": {"build": {"archetype": "Weapon Damage"}},
    }


def source() -> dict[str, Any]:
    return {
        "snapshot_manifest": {
            "snapshot_id": "1" * 64,
            "client_version": 123,
            "match_mode": "ranked",
            "game_mode": "normal",
            "rank_range": {},
            "as_of_timestamp": 1,
        },
        "source_context_sha256": "6" * 64,
        "patch": {},
        "exclusions": [{"hero_id": 13, "reason": "incomplete mechanics"}],
    }


def test_generator_contract_has_no_model_or_prompt_option() -> None:
    assert generate_narratives.GENERATOR_VERSION == NARRATIVE_GENERATOR_VERSION == 1

    with pytest.raises(SystemExit):
        generate_narratives.parse_args([
            "--input",
            "context.json",
            "--output",
            "narratives.json",
            "--model",
            "unused-model",
        ])


def test_deterministic_entry_copies_identity_and_uses_pinned_context() -> None:
    entry = generate_narratives.deterministic_narrative(packet())

    assert entry == {
        "hero_id": 12,
        "path_id": "default",
        "hero": "Kelvin",
        "snapshot_id": "1" * 64,
        "policy_id": "2" * 64,
        "context_sha256": "3" * 64,
        "narrative_basis_sha256": "5" * 64,
        "generator_version": 1,
        "build_description": (
            "Kelvin: Protect allies. Control space with ice and protect the team. "
            "Follow the shown Weapon Damage CORE order and max Frozen Shelter first. "
            "Use conditional cards only when their VS line applies; all optional rows "
            "stay outside Queue."
        ),
    }


def test_reuse_requires_the_exact_deterministic_result() -> None:
    hero = packet()
    key = (12, "default")
    entry = generate_narratives.deterministic_narrative(hero)

    assert generate_narratives.validated_reusable_entries(
        {key: entry},
        {key: hero},
    ) == {key: entry}

    edited = {**entry, "build_description": "Edited description."}
    assert not generate_narratives.validated_reusable_entries(
        {key: edited},
        {key: hero},
    )


def test_document_is_sorted_complete_and_has_no_model_metadata() -> None:
    first = packet()
    second = copy.deepcopy(first)
    second.update({"hero_id": 11, "hero": "Abrams"})

    document = generate_narratives.generate_document(
        source(),
        [first, second],
        {},
        include_all_exclusions=True,
        force=False,
    )

    assert document["generator"] == "deadlock-build-sync deterministic description"
    assert document["generator_version"] == 1
    assert "model" not in document
    assert "prompt_version" not in document
    assert document["requested_hero_ids"] == [11, 12, 13]
    assert [entry["hero_id"] for entry in document["heroes"]] == [11, 12]


def test_selector_rejects_unknown_hero() -> None:
    document = {"heroes": [packet()]}

    assert (
        generate_narratives._selected_heroes(document, ["Kelvin"])[0]["hero_id"] == 12
    )
    with pytest.raises(generate_narratives.GenerationError, match="not found"):
        generate_narratives._selected_heroes(document, ["Abrams"])


def test_missing_role_fails_closed() -> None:
    hero = packet()
    hero["hero_mechanics"] = {"description": {}}
    hero["policy"] = {}

    with pytest.raises(generate_narratives.GenerationError, match="hero role"):
        generate_narratives.deterministic_narrative(hero)
