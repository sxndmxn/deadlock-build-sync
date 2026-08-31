import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from deadlock_build_sync.narratives import NARRATIVE_GENERATOR_VERSION
from deadlock_build_sync.offline.config import sha256_json
from deadlock_build_sync.value_validation import require_object_rows
from scripts import generate_narratives


def packet() -> dict[str, object]:
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


def source() -> dict[str, object]:
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


def test_document_is_sorted_complete_and_has_no_model_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = packet()
    second = copy.deepcopy(first)
    second.update({"hero_id": 11, "hero": "Abrams"})
    generated_at = datetime(2026, 1, 2, tzinfo=UTC)

    class FixedDatetime:
        @staticmethod
        def now(_timezone: object) -> datetime:
            return generated_at

    monkeypatch.setattr(generate_narratives, "datetime", FixedDatetime)

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
    heroes = require_object_rows(document["heroes"])
    assert [entry["hero_id"] for entry in heroes] == [11, 12]
    assert sha256_json(document) == (
        "8ff0c92eb04b499f90705e329541680c29916469a9be40100a1f83deb9bdab1c"
    )


def test_selector_rejects_unknown_hero() -> None:
    document: dict[str, object] = {"heroes": [packet()]}

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


def test_load_object_wraps_read_json_and_root_errors(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(generate_narratives.GenerationError, match="could not read"):
        generate_narratives._load_object(missing)

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{", encoding="utf-8")
    with pytest.raises(generate_narratives.GenerationError, match="could not read"):
        generate_narratives._load_object(invalid)

    invalid.write_text("[]", encoding="utf-8")
    with pytest.raises(generate_narratives.GenerationError, match="JSON object"):
        generate_narratives._load_object(invalid)


def test_selected_heroes_rejects_missing_and_malformed_arrays() -> None:
    with pytest.raises(generate_narratives.GenerationError, match="heroes array"):
        generate_narratives._selected_heroes({}, None)
    with pytest.raises(generate_narratives.GenerationError, match="heroes array"):
        generate_narratives._selected_heroes({"heroes": [packet(), 1]}, None)
    assert generate_narratives._selected_heroes({"heroes": [packet()]}, None) == [
        packet()
    ]
    assert (
        generate_narratives._selected_heroes({"heroes": [packet()]}, ["12"])[0]["hero"]
        == "Kelvin"
    )


@pytest.mark.parametrize(
    "entry",
    [
        {},
        {"hero_id": "12", "path_id": "default"},
        {"hero_id": 12, "path_id": ""},
    ],
)
def test_build_key_rejects_incomplete_identity(entry: dict[str, object]) -> None:
    assert generate_narratives._build_key(entry) is None


def test_existing_entries_ignores_missing_malformed_and_invalid_rows(
    tmp_path: Path,
) -> None:
    path = tmp_path / "narratives.json"
    assert generate_narratives._existing_entries(path) == {}

    path.write_text(json.dumps({"heroes": "bad"}), encoding="utf-8")
    assert generate_narratives._existing_entries(path) == {}

    path.write_text(
        json.dumps({"heroes": [{"hero_id": 12}, packet()]}),
        encoding="utf-8",
    )
    assert set(generate_narratives._existing_entries(path)) == {(12, "default")}


def test_deterministic_narrative_requires_every_identity_field() -> None:
    hero = packet()
    hero["policy_id"] = ""
    with pytest.raises(generate_narratives.GenerationError, match="exact description"):
        generate_narratives.deterministic_narrative(hero)


def test_reusable_entries_skip_missing_and_invalid_source_heroes() -> None:
    key = (12, "default")
    hero = packet()
    entry = generate_narratives.deterministic_narrative(hero)
    invalid = copy.deepcopy(hero)
    invalid["policy_id"] = ""

    assert generate_narratives.validated_reusable_entries({key: entry}, {}) == {}
    assert (
        generate_narratives.validated_reusable_entries(
            {key: entry},
            {key: invalid},
        )
        == {}
    )


def test_artifact_document_requires_manifest() -> None:
    with pytest.raises(
        generate_narratives.GenerationError, match="no snapshot manifest"
    ):
        generate_narratives._artifact_document({}, {}, requested_hero_ids=set())


def test_force_generation_does_not_reuse_and_limits_exclusions(
    capsys: pytest.CaptureFixture[str],
) -> None:
    hero = packet()
    key = (12, "default")
    existing = {key: generate_narratives.deterministic_narrative(hero)}

    document = generate_narratives.generate_document(
        source(),
        [hero],
        existing,
        include_all_exclusions=False,
        force=True,
    )

    assert document["requested_hero_ids"] == [12]
    assert document["exclusions"] == []
    assert "write Kelvin" in capsys.readouterr().err


def test_main_writes_document_and_reports_generation_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_path = tmp_path / "context.json"
    output_path = tmp_path / "narratives.json"
    input_path.write_text(json.dumps({"heroes": [packet()]}), encoding="utf-8")
    monkeypatch.setattr(
        generate_narratives,
        "validate_strategy_context_document",
        lambda _source: None,
    )
    monkeypatch.setattr(
        generate_narratives,
        "generate_document",
        lambda *_args, **_kwargs: {"heroes": [packet()]},
    )

    assert (
        generate_narratives.main([
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        ])
        == 0
    )
    assert "Wrote 1 description" in capsys.readouterr().out

    monkeypatch.setattr(
        generate_narratives,
        "generate_document",
        lambda *_args, **_kwargs: {},
    )
    assert (
        generate_narratives.main([
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        ])
        == 1
    )
    assert "generated artifact has no heroes array" in capsys.readouterr().err
