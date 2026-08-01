from argparse import Namespace
from pathlib import Path
from typing import Any

import pytest

from scripts import generate_narratives


def _valid_context_and_response() -> tuple[dict[str, Any], dict[str, Any]]:
    hero = {
        "hero_id": 12,
        "hero": "Kelvin",
        "context_sha256": "a" * 64,
        "kit_basis_sha256": "d" * 64,
        "narrative_basis_sha256": "b" * 64,
        "abilities": [
            {
                "ability_id": index,
                "ability": f"Ability {quarter}",
                "stats": [{"label": "Damage", "value": index * 10}],
            }
            for index, quarter in enumerate(generate_narratives.QUARTERS, start=1)
        ],
        "ability_path": {
            "steps": [
                {
                    "quarter": index,
                    "ability": f"Ability {quarter}",
                    "upgrade": "UNLOCK",
                }
                for index, quarter in enumerate(generate_narratives.QUARTERS, start=1)
            ]
        },
        "tiers": {
            quarter: [{"item": f"Item {quarter}"}]
            for quarter in generate_narratives.QUARTERS
        },
        "duration_curve": {
            "shape": "LATE_SCALING",
            "strongest_phase": "LATE (45m+)",
            "weakest_phase": "EARLY (<30m)",
        },
    }
    response = {
        "hero_id": 12,
        "context_sha256": "a" * 64,
        "narrative_basis_sha256": "b" * 64,
        "tactical_profile": {
            "primary_role": "control support",
            "fight_role": "Control a committed fight and protect allied pressure.",
            "economy_plan": "Farm safely, then group for coordinated objectives.",
            "power_spikes": [
                {
                    "quarter": "III",
                    "trigger": "Item III with Ability III UNLOCK",
                    "tactical_unlock": (
                        "Repeated control permits coordinated objective pressure."
                    ),
                }
            ],
            "duration_plan": {
                "shape": "LATE_SCALING",
                "strongest_phase": "LATE (45m+)",
                "weakest_phase": "EARLY (<30m)",
                "macro_plan": "Scale safely and convert clean objectives.",
                "late_build_response": "REINFORCE",
                "response_reason": "Late items reinforce control and protection.",
            },
        },
        "build_summary": "Control fights, protect allies, and convert objectives.",
        "quarters": {
            "I": (
                "TIER I: Use Item I with Ability I when trading, then hold a safe "
                "position."
            ),
            "II": (
                "TIER II: Rotate with Item II and Ability II when allies group for "
                "a fight."
            ),
            "III": (
                "TIER III: POWER SPIKE — Item III with Ability III UNLOCK "
                "permits objective pressure when allies group; preserve economy "
                "between attempts."
            ),
            "IV": (
                "TIER IV: CURVE RESPONSE — REINFORCE. Use Item IV with Ability IV "
                "and close after a won fight."
            ),
        },
    }
    return hero, response


def test_kit_context_contains_only_ability_evidence() -> None:
    hero, _ = _valid_context_and_response()

    context = generate_narratives.kit_context(hero)

    assert context["kit_basis_sha256"] == "d" * 64
    assert len(context["abilities"]) == 4
    assert "tiers" not in context
    assert "duration_curve" not in context


def test_binds_model_identity_to_the_invocation_context() -> None:
    response = {
        "hero_id": 99,
        "kit_basis_sha256": "0" * 64,
        "combat_pattern": "Keep this model-authored field.",
    }
    source = {"hero_id": 12, "kit_basis_sha256": "d" * 64}

    bound = generate_narratives.bind_response_identity(
        response,
        source,
        ("hero_id", "kit_basis_sha256"),
    )

    assert bound["hero_id"] == 12
    assert bound["kit_basis_sha256"] == "d" * 64
    assert bound["combat_pattern"] == "Keep this model-authored field."


def test_normalizes_presentation_only_sentence_endings() -> None:
    response = {
        "quarters": {"I": "TIER I: Hold lane", "II": "TIER II: Rotate!"},
        "tactical_profile": {
            "power_spikes": [
                {
                    "quarter": "II",
                    "trigger": "An item and ability",
                    "tactical_unlock": "Commit after the setup lands",
                }
            ]
        },
    }

    normalized = generate_narratives.normalize_narrative_response(response)

    assert normalized["quarters"] == {
        "I": "TIER I: Hold lane.",
        "II": "TIER II: Rotate!",
    }
    assert (
        normalized["tactical_profile"]["power_spikes"][0]["tactical_unlock"]
        == "Commit after the setup lands."
    )
    assert response["quarters"]["I"] == "TIER I: Hold lane"


def test_generation_retries_a_semantic_validation_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hero, response = _valid_context_and_response()
    attempts = 0

    def fake_run_codex(*_args: object, **_kwargs: object) -> dict[str, Any]:
        nonlocal attempts
        attempts += 1
        return response

    def validate(
        candidate: dict[str, Any],
        _context: dict[str, Any],
    ) -> dict[str, Any]:
        if attempts == 1:
            raise generate_narratives.GenerationError("missing active instruction")
        return candidate

    monkeypatch.setattr(generate_narratives, "run_codex", fake_run_codex)

    validated = generate_narratives.generate_validated_response(
        hero,
        hero,
        generate_narratives.GenerationStage(
            schema_path=tmp_path / "schema.json",
            model="test-model",
            prompt="test prompt",
            identity_fields=(
                "hero_id",
                "context_sha256",
                "narrative_basis_sha256",
            ),
            validator=validate,
            label="test narrative",
            max_attempts=2,
        ),
    )

    assert attempts == 2
    assert validated["hero_id"] == hero["hero_id"]


def test_validates_grounded_kit_profile() -> None:
    hero, _ = _valid_context_and_response()
    response = {
        "hero_id": 12,
        "kit_basis_sha256": "d" * 64,
        "primary_role": "mobile control initiator",
        "combat_pattern": "Enter after setup, control a target, and reset safely.",
        "economy_tendencies": "Prioritize safe income until the ordered control tools unlock.",
        "scaling_profile": "Later upgrades deepen control and improve repeated fight access.",
        "ability_roles": [
            {
                "ability_id": index,
                "ability": f"Ability {quarter}",
                "tactical_role": "Creates a supplied and explicitly grounded fight option.",
                "scaling_hooks": "Its labeled damage and ordered upgrades define its scaling.",
            }
            for index, quarter in enumerate(generate_narratives.QUARTERS, start=1)
        ],
        "synergies": [
            "Ability I creates the setup that Ability II can safely convert."
        ],
        "uncertainties": [],
    }

    validated = generate_narratives.validate_kit_response(response, hero)

    assert validated["prompt_version"] == generate_narratives.KIT_PROMPT_VERSION
    assert validated["ability_roles"][3]["ability_id"] == 4


def test_rejects_kit_profile_that_changes_an_ability() -> None:
    hero, _ = _valid_context_and_response()
    response = {
        "hero_id": 12,
        "kit_basis_sha256": "d" * 64,
        "primary_role": "control",
        "combat_pattern": "Use the supplied abilities to control committed fights.",
        "economy_tendencies": "Use safe income windows before taking coordinated fights.",
        "scaling_profile": "The supplied upgrade order adds later tactical options.",
        "ability_roles": [
            {
                "ability_id": index,
                "ability": "Invented" if index == 4 else f"Ability {quarter}",
                "tactical_role": "Creates one explicitly supplied tactical option.",
                "scaling_hooks": "Uses only the supplied description and labeled stats.",
            }
            for index, quarter in enumerate(generate_narratives.QUARTERS, start=1)
        ],
        "synergies": ["Ability I sets up Ability II using supplied mechanics."],
        "uncertainties": [],
    }

    with pytest.raises(generate_narratives.GenerationError, match="changed an ability"):
        generate_narratives.validate_kit_response(response, hero)


def test_supplied_name_match_allows_possessive_suffix() -> None:
    assert generate_narratives._mentions_item(  # ruff: ignore[private-member-access]
        "Rabbit Hex's final upgrade",
        "Rabbit Hex",
    )


@pytest.mark.parametrize(
    ("trigger", "error"),
    [
        (
            "Ability III UNLOCK",
            "exactly one top-three same-tier item",
        ),
        (
            "Item IV with Ability III UNLOCK",
            "exactly one top-three same-tier item",
        ),
        (
            "Item III with Ability IV UNLOCK",
            "one real same-tier ability milestone",
        ),
    ],
)
def test_rejects_ungrounded_power_spike_trigger(trigger: str, error: str) -> None:
    hero, response = _valid_context_and_response()
    response["tactical_profile"]["power_spikes"][0]["trigger"] = trigger

    with pytest.raises(generate_narratives.GenerationError, match=error):
        generate_narratives.validate_response(response, hero)


def test_rejects_truncated_power_spike_unlock() -> None:
    hero, response = _valid_context_and_response()
    response["tactical_profile"]["power_spikes"][0]["tactical_unlock"] = (
        "Repeated control permits coordinated objective pressure"
    )

    with pytest.raises(
        generate_narratives.GenerationError,
        match="did not finish its tactical unlock",
    ):
        generate_narratives.validate_response(response, hero)


def test_rejects_ability_before_its_first_path_unlock() -> None:
    hero, response = _valid_context_and_response()
    response["quarters"]["I"] += " Do not use Ability II yet."

    with pytest.raises(generate_narratives.GenerationError, match="future ability"):
        generate_narratives.validate_response(response, hero)


def test_rejects_tier_without_decision_condition() -> None:
    hero, response = _valid_context_and_response()
    response["quarters"]["IV"] = (
        "TIER IV: CURVE RESPONSE — REINFORCE. Use Item IV and close the game."
    )

    with pytest.raises(
        generate_narratives.GenerationError,
        match="omitted a decision condition in tier IV",
    ):
        generate_narratives.validate_response(response, hero)


def test_rejects_late_scaling_tier_without_economy_priority() -> None:
    hero, response = _valid_context_and_response()
    response["quarters"]["III"] = (
        "TIER III: POWER SPIKE — Item III with Ability III UNLOCK improves Spirit "
        "scaling and permits objective pressure when allies group."
    )

    with pytest.raises(
        generate_narratives.GenerationError,
        match="did not preserve economy in tier III",
    ):
        generate_narratives.validate_response(response, hero)


def test_rejects_tier_without_same_quarter_ability() -> None:
    hero, response = _valid_context_and_response()
    response["quarters"]["II"] = (
        "TIER II: Rotate with Item II when allies group for a fight."
    )

    with pytest.raises(
        generate_narratives.GenerationError,
        match="omitted a tier II ability-path ability",
    ):
        generate_narratives.validate_response(response, hero)


def test_rejects_charge_item_for_non_charge_ability() -> None:
    hero, response = _valid_context_and_response()
    hero["tiers"]["III"][0]["stats"] = [
        {"label": "Bonus Ability Charges"},
        {"label": "Cooldown Reduction For Charged Abilities"},
    ]

    with pytest.raises(
        generate_narratives.GenerationError,
        match="charge-specific item",
    ):
        generate_narratives.validate_response(response, hero)


def test_accepts_charge_item_for_charge_ability() -> None:
    hero, response = _valid_context_and_response()
    hero["tiers"]["III"][0]["stats"] = [
        {"label": "Bonus Ability Charges"},
        {"label": "Cooldown Reduction For Charged Abilities"},
    ]
    hero["abilities"][2]["stats"] = [{"label": "Ability Charges", "value": 1}]

    validated = generate_narratives.validate_response(response, hero)

    assert validated["tactical_profile"] == response["tactical_profile"]


def test_accepts_charge_item_when_an_upgrade_allows_charges() -> None:
    hero, response = _valid_context_and_response()
    hero["tiers"]["III"][0]["stats"] = [
        {"label": "Bonus Ability Charges"},
        {"label": "Cooldown Reduction For Charged Abilities"},
    ]
    hero["abilities"][2]["description"] = {"t3_desc": "Allow Charges"}

    validated = generate_narratives.validate_response(response, hero)

    assert validated["tactical_profile"] == response["tactical_profile"]


def test_does_not_treat_charges_up_as_ability_charges() -> None:
    hero, response = _valid_context_and_response()
    hero["tiers"]["III"][0]["description"] = {
        "desc": "The imbued ability charges up over time with bonus damage."
    }

    validated = generate_narratives.validate_response(response, hero)

    assert validated["tactical_profile"] == response["tactical_profile"]


def test_rejects_hero_context_without_complete_ability_path() -> None:
    hero, _ = _valid_context_and_response()
    hero["ability_path"] = None

    with pytest.raises(
        generate_narratives.GenerationError,
        match="complete ability path",
    ):
        generate_narratives.validate_hero_context(hero)


def test_main_rewrites_artifact_when_all_narratives_are_reused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schema = tmp_path / "schema.json"
    schema.write_text("{}", encoding="utf-8")
    output = tmp_path / "narratives.json"
    hero = {"hero_id": 12, "hero": "Kelvin"}
    entry = {"hero_id": 12, "hero": "Kelvin"}
    source = {
        "schema_version": 3,
        "source_context_sha256": "a" * 64,
        "patch": {"published_at": "2026-01-01T00:00:00Z"},
        "heroes": [hero],
    }
    writes: list[dict[str, Any]] = []

    monkeypatch.setattr(
        generate_narratives,
        "parse_args",
        lambda: Namespace(
            input=tmp_path / "context.json",
            output=output,
            schema=schema,
            hero=None,
            model=None,
            force=False,
        ),
    )
    monkeypatch.setattr(generate_narratives, "_load_object", lambda _path: source)
    monkeypatch.setattr(
        generate_narratives,
        "validate_strategy_context_document",
        lambda _source: None,
    )
    monkeypatch.setattr(
        generate_narratives,
        "validate_hero_context",
        lambda _hero: None,
    )
    monkeypatch.setattr(
        generate_narratives,
        "_existing_entries",
        lambda _path: {12: entry},
    )
    monkeypatch.setattr(
        generate_narratives,
        "validated_reusable_entries",
        lambda _existing, _heroes: {12: entry},
    )
    monkeypatch.setattr(
        generate_narratives,
        "_write_artifact",
        lambda _path, document: writes.append(document),
    )

    assert generate_narratives.main() == 0
    assert len(writes) == 1
    assert writes[0]["heroes"] == [entry]
    assert writes[0]["patch"] == source["patch"]


def test_reuses_valid_narrative_when_only_full_context_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = {
        "hero_id": 12,
        "prompt_version": generate_narratives.PROMPT_VERSION,
        "context_sha256": "a" * 64,
        "narrative_basis_sha256": "b" * 64,
    }
    hero = {
        "hero_id": 12,
        "context_sha256": "c" * 64,
        "narrative_basis_sha256": "b" * 64,
    }

    def validate(
        response: dict[str, Any],
        live_hero: dict[str, Any],
        *,
        require_context_match: bool = True,
    ) -> dict[str, Any]:
        assert response is entry
        assert live_hero is hero
        assert not require_context_match
        return response

    monkeypatch.setattr(generate_narratives, "validate_response", validate)

    reusable = generate_narratives.validated_reusable_entries(
        {12: entry},
        {12: hero},
    )

    assert reusable == {12: entry}


def test_does_not_reuse_narrative_when_basis_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = {
        "hero_id": 12,
        "prompt_version": generate_narratives.PROMPT_VERSION,
        "context_sha256": "a" * 64,
        "narrative_basis_sha256": "b" * 64,
    }
    hero = {
        "hero_id": 12,
        "context_sha256": "c" * 64,
        "narrative_basis_sha256": "d" * 64,
    }

    def reject_validation(*_args: object, **_kwargs: object) -> dict[str, Any]:
        pytest.fail("a mismatched basis must be rejected before validation")

    monkeypatch.setattr(
        generate_narratives,
        "validate_response",
        reject_validation,
    )

    reusable = generate_narratives.validated_reusable_entries(
        {12: entry},
        {12: hero},
    )

    assert not reusable


def test_does_not_reuse_invalid_existing_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = {
        "hero_id": 12,
        "prompt_version": generate_narratives.PROMPT_VERSION,
        "context_sha256": "a" * 64,
        "narrative_basis_sha256": "b" * 64,
    }
    hero = {
        "hero_id": 12,
        "context_sha256": "c" * 64,
        "narrative_basis_sha256": "b" * 64,
    }

    def reject_validation(*_args: object, **_kwargs: object) -> dict[str, Any]:
        raise generate_narratives.GenerationError("invalid existing entry")

    monkeypatch.setattr(
        generate_narratives,
        "validate_response",
        reject_validation,
    )

    reusable = generate_narratives.validated_reusable_entries(
        {12: entry},
        {12: hero},
    )

    assert not reusable


def test_migrates_previous_prompt_output_only_after_current_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = {
        "hero_id": 12,
        "prompt_version": 14,
        "narrative_basis_sha256": "b" * 64,
    }
    hero = {
        "hero_id": 12,
        "narrative_basis_sha256": "b" * 64,
    }

    def validate(
        candidate: dict[str, Any],
        _hero: dict[str, Any],
        *,
        require_context_match: bool,
    ) -> dict[str, Any]:
        assert candidate is entry
        assert not require_context_match
        return {**candidate, "prompt_version": generate_narratives.PROMPT_VERSION}

    monkeypatch.setattr(generate_narratives, "validate_response", validate)

    reusable = generate_narratives.validated_reusable_entries(
        {12: entry},
        {12: hero},
    )

    assert reusable[12]["prompt_version"] == generate_narratives.PROMPT_VERSION
