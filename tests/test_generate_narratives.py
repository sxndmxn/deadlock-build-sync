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
            "language_ceiling": "descriptive default projection, not a universal path",
            "steps": [
                {
                    "position": index,
                    "earliest_legal_level": index,
                    "ability_id": ability_id,
                    "ability": name,
                    "action": "UNLOCK" if index <= 4 else "UPGRADE_1",
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
        "policy": {"policy_id": "2" * 64, "nodes": []},
        "explainable_actions": [
            {
                "node_id": "core",
                "kind": "purchase",
                "action_id": 101,
                "action": "Frost Core",
                "evidence_ref": "item/101/purchase-events",
                "claim_class": "descriptive",
                "language_ceiling": ["observed"],
                "mechanics_refs": ["item/101"],
                "annotation": "",
            },
            {
                "node_id": "counter",
                "kind": "purchase",
                "action_id": 102,
                "action": "Reactive Barrier",
                "evidence_ref": "item/102/purchase-events",
                "claim_class": "descriptive",
                "language_ceiling": ["observed"],
                "mechanics_refs": ["item/102/burst-response"],
                "annotation": (
                    "If enemy 7's spirit pressure is material, choose Reactive Barrier "
                    "instead of Frost Core; use before committing; skip unless observed."
                ),
                "conditional_contract": {
                    "threat": "spirit_pressure",
                    "item_id": 102,
                    "item": "Reactive Barrier",
                    "comparator_item_id": 101,
                    "comparator_item": "Frost Core",
                    "enemy_hero_id": 7,
                    "mechanic_ref": "item/102/burst-response",
                    "legal_timing": "same observed decision opportunity",
                    "alternative": "Frost Core or save",
                    "replacement": "Choose Reactive Barrier instead of Frost Core.",
                    "execution_mode": "Use before committing.",
                    "failure_condition": "Skip unless spirit pressure is observed.",
                    "evidence_ref": "item/102/purchase-events",
                },
            },
        ],
        "projection": {
            "categories": [
                {
                    "name": "CORE — DEFAULT QUEUE",
                    "optional": False,
                    "items": [{"item_id": 101, "item": "Frost Core"}],
                },
                {
                    "name": "IF BURST",
                    "optional": True,
                    "items": [{"item_id": 102, "item": "Reactive Barrier"}],
                },
            ]
        },
    }
    response: dict[str, Any] = {
        "hero_id": 12,
        "snapshot_id": "1" * 64,
        "policy_id": "2" * 64,
        "context_sha256": "3" * 64,
        "narrative_basis_sha256": "5" * 64,
        "tactical_profile": {
            "primary_role": "Control support.",
            "fight_role": "Protect allied pressure and control committed enemies.",
            "economy_plan": "Take safe income, then group when allied pressure is ready.",
            "ending_duration_interpretation": {
                "estimand": "ending_duration_profile",
                "strongest_phase": "LATE (45m+)",
                "weakest_phase": "EARLY (<30m)",
                "plan": "Convert clean openings now while retaining options if play runs late.",
            },
        },
        "build_summary": (
            "Control committed fights around a compact default path, protect allied "
            "pressure, and recalculate when an observable defensive trigger appears."
        ),
        "action_explanations": [
            {
                "node_id": "core",
                "evidence_ref": "item/101/purchase-events",
                "instruction": "Use Frost Core as the coherent default purchase.",
            },
            {
                "node_id": "counter",
                "evidence_ref": "item/102/purchase-events",
                "instruction": (
                    "If enemy 7's spirit pressure is observed, choose Reactive Barrier over "
                    "Frost Core; use before committing; skip unless material."
                ),
            },
        ],
        "category_summaries": [
            {
                "category": "CORE — DEFAULT QUEUE",
                "summary": "Follow Frost Core as the minimal coherent default path.",
            },
            {
                "category": "IF BURST",
                "summary": (
                    "When burst is material, choose Reactive Barrier as a conditional "
                    "replacement rather than an automatic purchase."
                ),
            },
        ],
    }
    return packet, response


def test_generator_uses_installer_prompt_version() -> None:
    assert generate_narratives.PROMPT_VERSION == NARRATIVE_PROMPT_VERSION == 23


def test_kit_context_excludes_items_outcomes_and_policy() -> None:
    packet, _ = packet_and_response()

    context = generate_narratives.kit_context(packet)

    assert context["kit_basis_sha256"] == "4" * 64
    assert len(context["hero_mechanics"]["abilities"]) == 4
    assert "abilities" not in context
    assert "hero_description" not in context
    assert "projection" not in context
    assert "ending_duration_profile" not in context
    assert "policy" not in context


def test_synthesis_context_contains_only_selected_policy_evidence() -> None:
    source, _ = packet_and_response()
    source["policy"]["variant"] = "control"
    source["tiers"] = {
        "TIER 1": [
            {"item_id": 101, "item": "Frost Core"},
            {"item_id": 999, "item": "Unused"},
        ]
    }

    context = generate_narratives.synthesis_context(
        source,
        {"hero_id": 12, "kit_basis_sha256": "4" * 64},
        {"101": {"cost": 500}, "999": {"cost": 999}},
    )

    assert "tiers" not in context
    assert "matchups" not in context
    assert "policy" not in context
    assert [item["item_id"] for item in context["selected_action_mechanics"]] == [101]
    assert context["selected_action_mechanics"][0]["mechanics"] == {"cost": 500}
    assert context["hero_description"]["role"] == "Protect allies"
    assert context["policy_summary"]["variant"] == "control"


def test_rejects_legacy_ability_quarter() -> None:
    packet, _ = packet_and_response()
    packet["ability_policy"]["steps"][0]["quarter"] = 1

    with pytest.raises(
        generate_narratives.GenerationError, match="legal ability timeline"
    ):
        generate_narratives.validate_hero_context(packet)


def test_validates_closed_policy_explanation() -> None:
    packet, response = packet_and_response()

    validated = generate_narratives.validate_response(response, packet)

    assert validated["prompt_version"] == 23


def test_rejects_core_instruction_over_utf8_byte_budget() -> None:
    packet, response = packet_and_response()
    response["action_explanations"][0]["instruction"] = (
        "Use Frost Core " + "é" * 80 + "."
    )

    with pytest.raises(generate_narratives.GenerationError, match="165-byte"):
        generate_narratives.validate_response(response, packet)


def test_rejects_changed_snapshot_or_policy() -> None:
    packet, response = packet_and_response()
    response["policy_id"] = "9" * 64

    with pytest.raises(generate_narratives.GenerationError, match="changed policy_id"):
        generate_narratives.validate_response(response, packet)


def test_rejects_missing_or_reordered_action() -> None:
    packet, response = packet_and_response()
    response["action_explanations"].reverse()

    with pytest.raises(generate_narratives.GenerationError, match="closed action set"):
        generate_narratives.validate_response(response, packet)


def test_rejects_cross_category_item() -> None:
    packet, response = packet_and_response()
    response["category_summaries"][0]["summary"] += " Buy Reactive Barrier too."

    with pytest.raises(generate_narratives.GenerationError, match="cross-category"):
        generate_narratives.validate_response(response, packet)


def test_allows_exact_annotated_replacement_in_optional_summary() -> None:
    packet, response = packet_and_response()
    response["category_summaries"][1]["summary"] = (
        "When burst is material, choose Reactive Barrier instead of Frost Core as "
        "a conditional replacement, not an automatic Queue purchase."
    )

    validated = generate_narratives.validate_response(response, packet)

    assert "instead of Frost Core" in validated["category_summaries"][1]["summary"]


def test_rejects_optional_category_without_observable_condition() -> None:
    packet, response = packet_and_response()
    response["category_summaries"][1]["summary"] = (
        "Reactive Barrier is a conditional replacement and is never automatic."
    )

    with pytest.raises(generate_narratives.GenerationError, match="optional trigger"):
        generate_narratives.validate_response(response, packet)


@pytest.mark.parametrize(
    ("instruction", "reason"),
    [
        (
            "If enemy 7's spirit pressure is observed, choose Reactive Barrier over the default; use it; skip unless material.",
            "comparator",
        ),
        (
            "Against enemy 7's spirit pressure, choose Reactive Barrier over Frost Core; use it; skip unless material.",
            "trigger",
        ),
        (
            "If enemy 7's spirit pressure is observed, take Reactive Barrier with Frost Core; use it; skip unless material.",
            "replacement",
        ),
        (
            "If enemy 7's spirit pressure is observed, choose Reactive Barrier over Frost Core; keep observing; skip unless material.",
            "execution",
        ),
        (
            "If enemy 7's spirit pressure is observed, choose Reactive Barrier over Frost Core; use it while material.",
            "failure condition",
        ),
        (
            "If enemy 7's spirit pressure and healing are observed, choose Reactive Barrier over Frost Core; use it; skip unless material.",
            "invented a threat",
        ),
    ],
)
def test_rejects_incomplete_or_invented_conditional_contract(
    instruction: str,
    reason: str,
) -> None:
    packet, response = packet_and_response()
    response["action_explanations"][1]["instruction"] = instruction

    with pytest.raises(generate_narratives.GenerationError, match=reason):
        generate_narratives.validate_response(response, packet)


def test_tier_reference_menu_does_not_require_invented_trigger() -> None:
    packet, response = packet_and_response()
    packet["projection"]["categories"][1]["name"] = "TIER 1"
    response["category_summaries"][1] = {
        "category": "TIER 1",
        "summary": (
            "Reactive Barrier is a situational reference option, not an automatic "
            "purchase."
        ),
    }

    validated = generate_narratives.validate_response(response, packet)

    assert validated["category_summaries"][1]["category"] == "TIER 1"


def test_tier_reference_menu_rejects_buying_all_items() -> None:
    packet, response = packet_and_response()
    packet["projection"]["categories"][1]["name"] = "TIER 1"
    response["category_summaries"][1] = {
        "category": "TIER 1",
        "summary": "Buy all Reactive Barrier options from this situational menu.",
    }

    with pytest.raises(generate_narratives.GenerationError, match="all-item"):
        generate_narratives.validate_response(response, packet)


@pytest.mark.parametrize("phrase", ["improves win rate", "purchase-event volume"])
def test_rejects_causal_or_analytic_language(phrase: str) -> None:
    packet, response = packet_and_response()
    response["build_summary"] += f" It {phrase}."

    with pytest.raises(
        generate_narratives.GenerationError, match=r"claim|analytic-unit"
    ):
        generate_narratives.validate_response(response, packet)


def test_rejects_changed_ending_duration_estimand() -> None:
    packet, response = packet_and_response()
    response["tactical_profile"]["ending_duration_interpretation"][
        "strongest_phase"
    ] = "MID (30–45m)"

    with pytest.raises(generate_narratives.GenerationError, match="strongest_phase"):
        generate_narratives.validate_response(response, packet)


@pytest.mark.parametrize(
    "primary_role",
    [
        "Protect allies and control committed enemies",
        "Protect allies or56.",
        "Protect allies 和 control enemies.",
        "Protect allies\u2060 and control enemies.",
    ],
)
def test_rejects_incomplete_or_corrupted_primary_role(primary_role: str) -> None:
    packet, response = packet_and_response()
    response["tactical_profile"]["primary_role"] = primary_role

    with pytest.raises(generate_narratives.GenerationError, match=r"primary role"):
        generate_narratives.validate_response(response, packet)


def test_normalizes_only_sentence_endings() -> None:
    _, response = packet_and_response()
    response["build_summary"] = "A complete default plan"
    response["action_explanations"][0]["instruction"] = "Use Frost Core"

    normalized = generate_narratives.normalize_narrative_response(response)

    assert normalized["build_summary"] == "A complete default plan."
    assert normalized["action_explanations"][0]["instruction"] == "Use Frost Core."
    assert response["build_summary"] == "A complete default plan"


def test_binds_source_owned_row_identities_without_repairing_omissions() -> None:
    packet, response = packet_and_response()
    response["action_explanations"][0]["node_id"] = "changed"
    response["action_explanations"][0]["evidence_ref"] = "changed"
    response["category_summaries"][0]["category"] = "changed"

    bound = generate_narratives.bind_response_structure(response, packet)

    assert bound["action_explanations"][0]["node_id"] == "core"
    assert bound["action_explanations"][0]["evidence_ref"] == "item/101/purchase-events"
    assert bound["category_summaries"][0]["category"] == "CORE — DEFAULT QUEUE"

    truncated = {
        **response,
        "action_explanations": response["action_explanations"][:-1],
    }
    assert (
        len(
            generate_narratives.bind_response_structure(truncated, packet)[
                "action_explanations"
            ]
        )
        == 1
    )


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


def test_hero_pipelines_overlap_and_checkpoint_in_deterministic_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, _ = packet_and_response()
    second = copy.deepcopy(first)
    second.update({"hero_id": 13, "hero": "Viscous"})
    selected = [second, first]
    source = {
        "snapshot_manifest": {"snapshot_id": "1" * 64},
        "source_context_sha256": "6" * 64,
        "patch": {},
        "exclusions": [],
        "item_mechanics": {},
    }
    stage_order: dict[int, list[str]] = {12: [], 13: []}
    active = 0
    peak_active = 0
    lock = threading.Lock()
    kit_barrier = threading.Barrier(2)

    def fake_generate(
        _model_input: dict[str, Any],
        validation_context: dict[str, Any],
        stage: generate_narratives.GenerationStage,
        **_kwargs: object,
    ) -> dict[str, Any]:
        nonlocal active, peak_active
        hero_id = int(validation_context["hero_id"])
        is_kit = stage.prompt == generate_narratives.KIT_PROMPT
        with lock:
            active += 1
            peak_active = max(peak_active, active)
        if is_kit:
            kit_barrier.wait(timeout=1)
        with lock:
            if not is_kit:
                assert stage_order[hero_id] == ["kit"]
            stage_order[hero_id].append("kit" if is_kit else "synthesis")
            active -= 1
        if is_kit:
            return {
                "hero_id": hero_id,
                "kit_basis_sha256": validation_context["kit_basis_sha256"],
            }
        return {
            "hero_id": hero_id,
            "snapshot_id": validation_context["snapshot_id"],
            "policy_id": validation_context["policy_id"],
            "context_sha256": validation_context["context_sha256"],
            "narrative_basis_sha256": validation_context["narrative_basis_sha256"],
        }

    monkeypatch.setattr(
        generate_narratives,
        "generate_validated_response",
        fake_generate,
    )
    output = tmp_path / "narratives.json"
    kit_output = tmp_path / "kit-profiles.json"
    generated: dict[int, dict[str, Any]] = {}
    kit_profiles: dict[int, dict[str, Any]] = {}
    generate_narratives._generate_selected_heroes(
        selected,
        generated,
        kit_profiles,
        generate_narratives.GenerationRun(
            source=source,
            output=output,
            kit_output=kit_output,
            schema=tmp_path / "narrative.schema.json",
            kit_schema=tmp_path / "kit.schema.json",
            kit_model="kit-model",
            synthesis_model="synthesis-model",
            max_attempts=1,
            concurrency=2,
            force=True,
            requested_hero_ids={12, 13},
        ),
    )

    assert peak_active == 2
    assert stage_order == {12: ["kit", "synthesis"], 13: ["kit", "synthesis"]}
    assert [hero["hero_id"] for hero in selected] == [13, 12]
    assert [hero["hero_id"] for hero in json.loads(output.read_text())["heroes"]] == [
        12,
        13,
    ]
    assert [
        hero["hero_id"] for hero in json.loads(kit_output.read_text())["heroes"]
    ] == [12, 13]


def test_kit_validator_preserves_exact_abilities() -> None:
    packet, _ = packet_and_response()
    response = {
        "hero_id": 12,
        "kit_basis_sha256": "4" * 64,
        "primary_role": "control support",
        "combat_pattern": "Control committed enemies while protecting allied pressure.",
        "economy_tendencies": "Take safe income before grouping around allied pressure.",
        "scaling_profile": "Use the supplied legal upgrades to deepen control options.",
        "ability_roles": [
            {
                "ability_id": ability["id"],
                "ability": ability["name"],
                "tactical_role": "Use this supplied ability in the documented fight role.",
                "scaling_hooks": "Follow only its supplied properties and legal upgrades.",
            }
            for ability in packet["hero_mechanics"]["abilities"]
        ],
        "synergies": [
            "Frost Grenade can precede Arctic Beam using supplied mechanics."
        ],
        "uncertainties": [],
    }

    validated = generate_narratives.validate_kit_response(response, packet)

    assert validated["ability_roles"][3]["ability_id"] == 40


def test_reuse_requires_exact_context_snapshot_and_policy() -> None:
    packet, response = packet_and_response()
    response = generate_narratives.validate_response(response, packet)

    assert generate_narratives.validated_reusable_entries(
        {12: response},
        {12: packet},
    ) == {12: response}

    changed = {**packet, "context_sha256": "8" * 64}
    assert not generate_narratives.validated_reusable_entries(
        {12: response},
        {12: changed},
    )
