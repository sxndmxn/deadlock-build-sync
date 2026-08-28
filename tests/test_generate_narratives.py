import argparse
import copy
import json
import threading
from pathlib import Path
from typing import Any

import pytest

from deadlock_build_sync.narratives import NARRATIVE_PROMPT_VERSION
from scripts import generate_narratives


def packet_and_response() -> tuple[dict[str, Any], dict[str, Any]]:
    packet: dict[str, Any] = {
        "hero_id": 12,
        "path_id": "default",
        "path_label": "Weapon Damage",
        "hero": "Kelvin",
        "snapshot_id": "1" * 64,
        "policy_id": "2" * 64,
        "context_sha256": "3" * 64,
        "kit_basis_sha256": "4" * 64,
        "narrative_basis_sha256": "5" * 64,
        "hero_mechanics": {
            "description": {"role": "Protect allies", "playstyle": "Control space"},
            "abilities": [
                {"id": ability_id, "name": name, "description": {"desc": name}}
                for ability_id, name in (
                    (10, "Frost Grenade"),
                    (20, "Arctic Beam"),
                    (30, "Ice Path"),
                    (40, "Frozen Shelter"),
                )
            ],
        },
        "ability_policy": {
            "language_ceiling": "descriptive default projection",
            "steps": [
                {
                    "position": index,
                    "earliest_legal_level": index,
                    "ability_id": ability_id,
                    "ability": name,
                    "action": "UNLOCK",
                }
                for index, (ability_id, name) in enumerate(
                    (
                        (10, "Frost Grenade"),
                        (20, "Arctic Beam"),
                        (30, "Ice Path"),
                        (40, "Frozen Shelter"),
                    ),
                    start=1,
                )
            ],
        },
        "ending_duration_profile": {
            "estimand": "ending_duration_profile",
            "strongest_phase": "LATE (45m+)",
            "weakest_phase": "EARLY (<30m)",
        },
        "policy": {
            "variant": "control",
            "invariant_kit_id": "kit",
            "strategic_role": "control support",
            "abstentions": [],
        },
        "core": {
            "items": [
                {"item_id": 101, "item": "Frost Core"},
                {"item_id": 102, "item": "Titanic Magazine"},
            ]
        },
        "projection": {
            "categories": [
                {
                    "name": "CORE ITEMS",
                    "optional": False,
                    "items": [
                        {"item_id": 101, "item": "Frost Core"},
                        {"item_id": 102, "item": "Titanic Magazine"},
                    ],
                }
            ]
        },
        "interpretation_constraints": ["observational"],
        "explainable_actions": [],
    }
    response: dict[str, Any] = {
        "hero_id": 12,
        "path_id": "default",
        "snapshot_id": "1" * 64,
        "policy_id": "2" * 64,
        "context_sha256": "3" * 64,
        "narrative_basis_sha256": "5" * 64,
        "build_description": (
            "Control committed fights with Kelvin's space denial while the weapon "
            "CORE keeps steady pressure available between protective rotations."
        ),
    }
    return packet, response


def test_generator_uses_installer_prompt_version() -> None:
    assert generate_narratives.PROMPT_VERSION == NARRATIVE_PROMPT_VERSION == 25


def test_description_context_excludes_item_hover_and_outcome_evidence() -> None:
    packet, _ = packet_and_response()

    context = generate_narratives.synthesis_context(packet)

    assert context["hero_mechanics"] == packet["hero_mechanics"]
    assert context["core_items"] == [
        {"item_id": 101, "item": "Frost Core", "tier": None},
        {"item_id": 102, "item": "Titanic Magazine", "tier": None},
    ]
    assert context["path_label"] == "Weapon Damage"
    assert "explainable_actions" not in context
    assert "tiers" not in context
    assert "ending_duration_profile" not in context


def test_validates_build_description_only() -> None:
    packet, response = packet_and_response()

    validated = generate_narratives.validate_response(response, packet)

    assert validated["prompt_version"] == 25
    assert set(validated) == {
        "hero_id",
        "path_id",
        "hero",
        "snapshot_id",
        "policy_id",
        "context_sha256",
        "narrative_basis_sha256",
        "prompt_version",
        "build_description",
    }


def test_rejects_changed_snapshot_or_policy() -> None:
    packet, response = packet_and_response()
    response["policy_id"] = "9" * 64

    with pytest.raises(generate_narratives.GenerationError, match="changed policy_id"):
        generate_narratives.validate_response(response, packet)


@pytest.mark.parametrize(
    ("description", "reason"),
    [
        ("Too short.", "out-of-range"),
        (
            (
                "Control space with the supplied kit because this guarantees victories "
                "in every fight while keeping the supported path intact."
            ),
            "non-causal claim",
        ),
        (
            (
                "Control space through the supplied kit while following the observed "
                "purchase-event volume and keeping the supported path intact."
            ),
            "analytic-unit language",
        ),
        (
            (
                "Control space through the supplied kit⁠ while keeping the supported "
                "CORE path intact and protecting allied pressure in committed fights."
            ),
            "corrupted build description",
        ),
    ],
)
def test_rejects_invalid_build_description(description: str, reason: str) -> None:
    packet, response = packet_and_response()
    response["build_description"] = description

    with pytest.raises(generate_narratives.GenerationError, match=reason):
        generate_narratives.validate_response(response, packet)


def test_normalizes_only_description_sentence_ending() -> None:
    _, response = packet_and_response()
    response["build_description"] = response["build_description"].rstrip(".")

    normalized = generate_narratives.normalize_narrative_response(response)

    assert normalized["build_description"].endswith(".")
    assert not response["build_description"].endswith(".")


def test_generation_retries_semantic_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    packet, response = packet_and_response()
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
            raise generate_narratives.GenerationError("invalid first response")
        return candidate

    monkeypatch.setattr(generate_narratives, "run_codex", fake_run_codex)
    validated = generate_narratives.generate_validated_response(
        packet,
        packet,
        generate_narratives.GenerationStage(
            schema_path=tmp_path / "schema.json",
            model="test-model",
            prompt="prompt",
            identity_fields=("hero_id", "snapshot_id", "policy_id"),
            validator=validate,
            label="test",
            max_attempts=2,
        ),
    )

    assert attempts == 2
    assert validated["hero_id"] == 12


def test_rate_limit_halves_pressure_and_retries_affected_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    packet, response = packet_and_response()
    attempts = 0

    def fake_run_codex(*_args: object, **_kwargs: object) -> dict[str, Any]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise generate_narratives.GenerationError(
                "Codex failed with 429; Retry-After: 0 seconds"
            )
        return response

    monkeypatch.setattr(generate_narratives, "run_codex", fake_run_codex)
    monkeypatch.setattr(generate_narratives.random, "uniform", lambda *_args: 0.0)
    limiter = generate_narratives._RequestLimiter(4)
    validated = generate_narratives.generate_validated_response(
        packet,
        packet,
        generate_narratives.GenerationStage(
            schema_path=tmp_path / "schema.json",
            model="test-model",
            prompt="prompt",
            identity_fields=("hero_id", "snapshot_id", "policy_id"),
            validator=lambda candidate, _context: candidate,
            label="test",
            max_attempts=2,
        ),
        request_limiter=limiter,
    )

    assert attempts == 2
    assert limiter.current_limit == 2
    assert validated["hero_id"] == packet["hero_id"]


def test_build_descriptions_overlap_and_checkpoint_in_deterministic_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, response = packet_and_response()
    second = copy.deepcopy(first)
    second.update({"hero_id": 13, "hero": "Viscous"})
    selected = [second, first]
    source = {
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
        "exclusions": [],
    }
    active = 0
    peak_active = 0
    lock = threading.Lock()
    barrier = threading.Barrier(2)

    def fake_generate(
        _model_input: dict[str, Any],
        validation_context: dict[str, Any],
        _stage: generate_narratives.GenerationStage,
        **_kwargs: object,
    ) -> dict[str, Any]:
        nonlocal active, peak_active
        with lock:
            active += 1
            peak_active = max(peak_active, active)
        barrier.wait(timeout=1)
        with lock:
            active -= 1
        return {
            **response,
            "hero_id": validation_context["hero_id"],
            "path_id": validation_context["path_id"],
        }

    monkeypatch.setattr(
        generate_narratives,
        "generate_validated_response",
        fake_generate,
    )
    output = tmp_path / "narratives.json"
    run = generate_narratives._NarrativeGenerationRun(
        args=argparse.Namespace(
            force=True,
            model="description-model",
            max_attempts=1,
            concurrency=2,
            schema=tmp_path / "narrative.schema.json",
            output=output,
        ),
        source=source,
        selected_heroes=selected,
        requested_hero_ids={12, 13},
        generated_narratives={},
        artifact_lock=threading.Lock(),
        request_limiter=generate_narratives._RequestLimiter(2),
    )
    generate_narratives._generate_selected_narratives(run)

    assert peak_active == 2
    assert [hero["hero_id"] for hero in json.loads(output.read_text())["heroes"]] == [
        12,
        13,
    ]


def test_reuse_requires_exact_context_snapshot_and_policy() -> None:
    packet, response = packet_and_response()
    response = generate_narratives.validate_response(response, packet)

    assert generate_narratives.validated_reusable_entries(
        {(12, "default"): response},
        {(12, "default"): packet},
    ) == {(12, "default"): response}

    changed = {**packet, "context_sha256": "8" * 64}
    assert not generate_narratives.validated_reusable_entries(
        {(12, "default"): response},
        {(12, "default"): changed},
    )
