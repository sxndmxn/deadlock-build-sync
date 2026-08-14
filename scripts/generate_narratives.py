#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

from deadlock_build_sync.artifacts import atomic_write_json
from deadlock_build_sync.narratives import (
    DEFAULT_KIT_MODEL,
    DEFAULT_SYNTHESIS_MODEL,
    NARRATIVE_PROMPT_VERSION,
    NARRATIVE_SCHEMA_VERSION,
)
from deadlock_build_sync.purchase_guide import MAX_TACTICAL_INSTRUCTION_BYTES
from deadlock_build_sync.strategy_context import (
    StrategyContextError,
    validate_strategy_context_document,
)

SCHEMA_VERSION = NARRATIVE_SCHEMA_VERSION
PROMPT_VERSION = NARRATIVE_PROMPT_VERSION
REUSABLE_PROMPT_VERSIONS = frozenset({PROMPT_VERSION})
KIT_SCHEMA_VERSION = 1
KIT_PROMPT_VERSION = 3
DEFAULT_GENERATION_ATTEMPTS = 3
CONDITION_PATTERN = re.compile(
    r"\b(?:after|before|if|once|only|save|hold|until|when|while|unless|then)\b"
    r"|rather than|as soon as",
    re.IGNORECASE,
)
REFERENCE_MENU_PATTERN = re.compile(
    r"\b(?:adapt|menu|option|reference|situational)\w*\b", re.IGNORECASE
)
BUY_ALL_PATTERN = re.compile(
    r"\b(?:buy|get|purchase|take)\s+(?:all|every)\b", re.IGNORECASE
)
CAUSAL_PATTERN = re.compile(
    r"\b(?:causes?|guarantees?|adds? win rate|improves? win rate|"
    r"increases? (?:your )?chance|item impact)\b",
    re.IGNORECASE,
)
ANALYTICS_LEAK_PATTERN = re.compile(
    r"\b(?:pick rate|win rate|match count|net worth|purchase[- ]event|"
    r"confidence interval)\b",
    re.IGNORECASE,
)

KIT_PROMPT = """
Role: explain one Deadlock hero kit from a closed, patch-specific mechanics packet.

Use only hero_description, hero_mechanics, abilities, and ability_policy. Preserve
all supplied IDs and names. Explain each ability's tactical role and explicit
scaling hooks. Treat the reached-state ability policy as a descriptive default,
not proof that one universal order is optimal. Record uncertainty instead of
inventing mechanics, numeric effects, combos, matchups, or item interactions.

The input intentionally excludes items and outcomes. Return only the
schema-constrained JSON object.
""".strip()

PROMPT = """
Write a compact in-game Deadlock explanation for one closed build-policy packet.
Return only the schema-constrained JSON object.

Authority and scope:
- The deterministic policy, evidence claims, mechanics, guards, action IDs,
  Queue projection, and category membership are already final. Explain them;
  never add, remove, reorder, select, or change them.
- Copy hero_id, snapshot_id, policy_id, context_sha256, and
  narrative_basis_sha256 exactly.
- Use only supplied mechanics and preliminary_kit_analysis. Never invent a
  mechanic, numeric effect, combo, matchup, timing, target, or causal benefit.
- A descriptive association may be called observed or associated only. Never
  claim an item causes wins or improves win probability.
- ending_duration_profile describes outcomes among games ending in each phase;
  it is not a live power curve and is not permission to stall a winnable game.
  When both phase labels are UNAVAILABLE, state that the cohort is unsupported
  and make no phase-strength claim.
- Price tiers are price tiers. They are not early/mid/late phases and are never
  paired with equal quarters of the ability order.

tactical_profile:
- Give a hero-specific role, fight role, and economy plan grounded in the kit.
- Copy the ending-duration estimand and strongest/weakest phase labels exactly.
  Explain a conservative conversion plan without exposing rates or counts, or
  acknowledge the explicit unavailable state without inventing a phase.

build_summary:
- In 80–700 plain-text characters, describe the invariant role, eight-item CORE
  path, and the purpose of the four tier reference menus. Do not dump stats or
  analytics language.

action_explanations:
- Return every supplied explainable action exactly once, in supplied order.
- Copy node_id and evidence_ref. The instruction must name that supplied action.
- Keep every instruction within 165 UTF-8 bytes so the deterministic timing line
  can fit in the Steam hover.
- Explain only the supplied annotation/mechanics and stay within the claim's
  language ceiling. Conditional actions must retain their trigger, replacement,
  execution, and failure condition.

category_summaries:
- Return every supplied projection category exactly once, in supplied order.
- Copy the category name and mention only items in that category.
- CORE ITEMS is the automatic Queue. TIER 1–4 are optional reference menus:
  describe candidates conservatively, say to choose situationally, and never
  imply buying all options or claim adoption proves a counter/trigger.
- For any other optional policy branch, retain its supplied observable condition
  and exact replacement. Never invent an unsupplied condition.
- Finish every player-facing field with a complete sentence. No Markdown lists.
""".strip()


class GenerationError(RuntimeError):
    """Raised when model generation or deterministic admission fails."""


@dataclass(frozen=True)
class GenerationStage:
    """Configuration for one bounded Codex generation stage."""

    schema_path: Path
    model: str | None
    prompt: str
    identity_fields: tuple[str, ...]
    validator: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
    label: str
    max_attempts: int = DEFAULT_GENERATION_ATTEMPTS
    timeout_seconds: float = 1200
    normalizer: Callable[[dict[str, Any]], dict[str, Any]] | None = None


def _mentions_item(text: str, item_name: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(item_name)}(?!\w)", text) is not None


def _context_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_context_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_context_text(item) for item in value)
    if isinstance(value, str | int | float):
        return str(value)
    return ""


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def bind_response_identity(
    response: dict[str, Any],
    source: dict[str, Any],
    fields: tuple[str, ...],
) -> dict[str, Any]:
    """Bind invocation-owned identity fields before semantic validation.

    Returns:
        A shallow response copy with source-owned identities restored.

    """
    return {**response, **{field: source.get(field) for field in fields}}


def generate_validated_response(
    model_input: dict[str, Any],
    validation_context: dict[str, Any],
    stage: GenerationStage,
) -> dict[str, Any]:
    """Generate and validate one response with bounded retries.

    Returns:
        The first model response admitted by the deterministic validator.

    Raises:
        ValueError: If no generation attempt is permitted.
        GenerationError: If every attempt fails generation or validation.

    """
    if stage.max_attempts < 1:
        raise ValueError("max_attempts must be at least one")
    last_error: GenerationError | None = None
    for attempt in range(1, stage.max_attempts + 1):
        try:
            response = run_codex(
                model_input,
                schema_path=stage.schema_path,
                model=stage.model,
                prompt=stage.prompt,
                timeout_seconds=stage.timeout_seconds,
            )
            response = bind_response_identity(
                response,
                validation_context,
                stage.identity_fields,
            )
            if stage.normalizer is not None:
                response = stage.normalizer(response)
            return stage.validator(response, validation_context)
        except GenerationError as error:
            last_error = error
            if attempt < stage.max_attempts:
                print(
                    f"retry {stage.label} ({attempt + 1}/{stage.max_attempts}): {error}",
                    file=sys.stderr,
                )
    raise GenerationError(
        f"{stage.label} failed after {stage.max_attempts} attempt(s): {last_error}"
    ) from last_error


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _finish_sentence(value: Any) -> Any:
    if not isinstance(value, str) or not value.strip():
        return value
    stripped = value.strip()
    return stripped if stripped[-1] in ".!?" else stripped + "."


def normalize_narrative_response(response: dict[str, Any]) -> dict[str, Any]:
    """Normalize presentation-only sentence endings before strict validation.

    Returns:
        A response copy with complete player-facing sentences.

    """
    normalized = {**response}
    for field in ("build_summary",):
        if field in normalized:
            normalized[field] = _finish_sentence(normalized[field])
    tactical = response.get("tactical_profile")
    if isinstance(tactical, dict):
        normalized_tactical = {**tactical}
        for field in ("fight_role", "economy_plan"):
            if field in normalized_tactical:
                normalized_tactical[field] = _finish_sentence(
                    normalized_tactical[field]
                )
        duration = tactical.get("ending_duration_interpretation")
        if isinstance(duration, dict):
            normalized_tactical["ending_duration_interpretation"] = {
                **duration,
                "plan": _finish_sentence(duration.get("plan")),
            }
        normalized["tactical_profile"] = normalized_tactical
    for field, text_field in (
        ("action_explanations", "instruction"),
        ("category_summaries", "summary"),
    ):
        rows = response.get(field)
        if isinstance(rows, list):
            normalized[field] = [
                {**row, text_field: _finish_sentence(row.get(text_field))}
                if isinstance(row, dict)
                else row
                for row in rows
            ]
    return normalized


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate reviewed Deadlock build explanations with Codex."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--schema",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "schemas/narrative-response.schema.json",
    )
    parser.add_argument(
        "--kit-schema",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "schemas/kit-analysis-response.schema.json",
    )
    parser.add_argument(
        "--kit-output",
        type=Path,
        help="reusable ability-only kit profiles (default: beside --output)",
    )
    parser.add_argument(
        "--hero",
        action="append",
        help="limit generation to a hero name or numeric ID; repeatable",
    )
    parser.add_argument(
        "--kit-model",
        default=DEFAULT_KIT_MODEL,
        help=f"kit-analysis model (default: {DEFAULT_KIT_MODEL})",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_SYNTHESIS_MODEL,
        help=f"final synthesis model (default: {DEFAULT_SYNTHESIS_MODEL})",
    )
    parser.add_argument(
        "--max-attempts",
        type=positive_int,
        default=DEFAULT_GENERATION_ATTEMPTS,
        help=f"generation attempts per stage (default: {DEFAULT_GENERATION_ATTEMPTS})",
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args(argv)


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise GenerationError(f"could not read {path}: {error}") from error
    if not isinstance(value, dict):
        raise GenerationError(f"{path} did not contain a JSON object")
    return value


def _selected_heroes(
    document: dict[str, Any],
    selectors: list[str] | None,
) -> list[dict[str, Any]]:
    heroes = document.get("heroes")
    if not isinstance(heroes, list) or not all(
        isinstance(hero, dict) for hero in heroes
    ):
        raise GenerationError("strategy context is missing its heroes array")
    if not selectors:
        return heroes
    normalized = {selector.casefold().replace(" ", "") for selector in selectors}
    selected = [
        hero
        for hero in heroes
        if str(hero.get("hero_id")) in normalized
        or str(hero.get("hero") or "").casefold().replace(" ", "") in normalized
    ]
    matched = {
        value
        for hero in selected
        for value in (
            str(hero.get("hero_id")),
            str(hero.get("hero") or "").casefold().replace(" ", ""),
        )
    }
    missing = normalized - matched
    if missing:
        raise GenerationError(
            f"hero selector(s) not found: {', '.join(sorted(missing))}"
        )
    return selected


def _abilities(hero: dict[str, Any]) -> list[dict[str, Any]]:
    mechanics = hero.get("hero_mechanics")
    nested = mechanics.get("abilities") if isinstance(mechanics, dict) else None
    abilities = nested if isinstance(nested, list) else hero.get("abilities")
    return [ability for ability in abilities or [] if isinstance(ability, dict)]


def _ability_identity(ability: dict[str, Any]) -> tuple[int | None, str]:
    raw_id = ability.get("id", ability.get("ability_id"))
    raw_name = ability.get("name", ability.get("ability"))
    return (int(raw_id) if isinstance(raw_id, int) else None, str(raw_name or ""))


def validate_hero_context(hero: dict[str, Any]) -> None:
    """Reject packets that cannot support a closed-policy explanation.

    Raises:
        GenerationError: If identity, mechanics, policy, or projection is incomplete.

    """
    name = str(hero.get("hero") or hero.get("hero_id") or "unknown")
    identity_fields = (
        "snapshot_id",
        "policy_id",
        "context_sha256",
        "kit_basis_sha256",
        "narrative_basis_sha256",
    )
    if not isinstance(hero.get("hero_id"), int) or any(
        not _is_sha256(hero.get(field)) for field in identity_fields
    ):
        raise GenerationError(f"strategy context omitted exact identity for {name}")
    abilities = _abilities(hero)
    if len(abilities) != 4 or any(
        _ability_identity(ability)[0] is None for ability in abilities
    ):
        raise GenerationError(
            f"strategy context omitted four current abilities for {name}"
        )
    ability_policy = hero.get("ability_policy")
    steps = ability_policy.get("steps") if isinstance(ability_policy, dict) else None
    if (
        not isinstance(steps, list)
        or not steps
        or any(
            not isinstance(step, dict)
            or not isinstance(step.get("earliest_legal_level"), int)
            or "quarter" in step
            for step in steps
        )
    ):
        raise GenerationError(
            f"strategy context omitted a legal ability timeline for {name}"
        )
    ending = hero.get("ending_duration_profile")
    if (
        not isinstance(ending, dict)
        or ending.get("estimand") != "ending_duration_profile"
    ):
        raise GenerationError(
            f"strategy context omitted the ending-duration estimand for {name}"
        )
    policy = hero.get("policy")
    actions = hero.get("explainable_actions")
    projection = hero.get("projection")
    categories = projection.get("categories") if isinstance(projection, dict) else None
    if not isinstance(policy, dict) or policy.get("policy_id") != hero.get("policy_id"):
        raise GenerationError(f"strategy context omitted the policy for {name}")
    if not isinstance(actions, list) or not actions:
        raise GenerationError(f"strategy context omitted policy actions for {name}")
    if not isinstance(categories, list) or not categories:
        raise GenerationError(
            f"strategy context omitted the Steam projection for {name}"
        )


def kit_context(hero: dict[str, Any]) -> dict[str, Any]:
    """Return only mechanics and legal ability evidence for the kit stage.

    Returns:
        The ability-only packet supplied to the first model stage.

    """
    return {
        "hero_id": hero.get("hero_id"),
        "hero": hero.get("hero"),
        "hero_description": hero.get("hero_description"),
        "kit_basis_sha256": hero.get("kit_basis_sha256"),
        "hero_mechanics": hero.get("hero_mechanics"),
        "abilities": _abilities(hero),
        "ability_policy": hero.get("ability_policy"),
    }


def synthesis_context(
    hero: dict[str, Any],
    kit_profile: dict[str, Any],
) -> dict[str, Any]:
    """Return the smallest closed packet needed to explain the final policy.

    Returns:
        Identity, tactical evidence, selected-action mechanics, and projection semantics.

    """
    actions = hero.get("explainable_actions")
    action_ids = (
        {
            action.get("action_id")
            for action in actions
            if isinstance(action, dict) and isinstance(action.get("action_id"), int)
        }
        if isinstance(actions, list)
        else set()
    )
    selected_mechanics = []
    tiers = hero.get("tiers")
    if isinstance(tiers, dict):
        for tier_items in tiers.values():
            if not isinstance(tier_items, list):
                continue
            selected_mechanics.extend(
                item
                for item in tier_items
                if isinstance(item, dict) and item.get("item_id") in action_ids
            )
    core = hero.get("core")
    if isinstance(core, dict) and isinstance(core.get("items"), list):
        selected_mechanics.extend(
            item
            for item in core["items"]
            if isinstance(item, dict) and item.get("item_id") in action_ids
        )
    selected_mechanics = list(
        {
            int(item["item_id"]): item
            for item in selected_mechanics
            if isinstance(item.get("item_id"), int)
        }.values()
    )
    policy = hero.get("policy")
    policy_summary = None
    if isinstance(policy, dict):
        policy_summary = {
            key: policy.get(key)
            for key in (
                "variant",
                "invariant_kit_id",
                "strategic_role",
                "abstentions",
            )
        }
    return {
        key: hero.get(key)
        for key in (
            "hero_id",
            "hero",
            "snapshot_id",
            "policy_id",
            "context_sha256",
            "narrative_basis_sha256",
            "hero_description",
            "ability_policy",
            "ending_duration_profile",
            "core",
            "explainable_actions",
            "projection",
            "interpretation_constraints",
        )
    } | {
        "policy_summary": policy_summary,
        "selected_action_mechanics": selected_mechanics,
        "preliminary_kit_analysis": kit_profile,
    }


def validate_kit_response(
    response: dict[str, Any],
    hero: dict[str, Any],
) -> dict[str, Any]:
    """Validate an ability-only profile without admitting invented identities.

    Returns:
        A normalized, fingerprint-bound kit explanation.

    Raises:
        GenerationError: If identities or supplied ability evidence changed.

    """
    name = str(hero.get("hero") or hero.get("hero_id") or "unknown")
    if response.get("hero_id") != hero.get("hero_id"):
        raise GenerationError(f"kit analysis changed hero_id for {name}")
    if response.get("kit_basis_sha256") != hero.get("kit_basis_sha256"):
        raise GenerationError(f"kit analysis changed kit_basis_sha256 for {name}")
    text_fields = (
        "primary_role",
        "combat_pattern",
        "economy_tendencies",
        "scaling_profile",
    )
    if any(
        not isinstance(response.get(field), str) or not response[field].strip()
        for field in text_fields
    ):
        raise GenerationError(f"kit analysis omitted its tactical profile for {name}")
    supplied = {
        ability_id: ability_name
        for ability in _abilities(hero)
        for ability_id, ability_name in (_ability_identity(ability),)
        if ability_id is not None
    }
    roles = response.get("ability_roles")
    if not isinstance(roles, list) or len(roles) != len(supplied):
        raise GenerationError(f"kit analysis omitted ability roles for {name}")
    normalized_roles: list[dict[str, Any]] = []
    seen: set[int] = set()
    for role in roles:
        if not isinstance(role, dict) or not isinstance(role.get("ability_id"), int):
            raise GenerationError(
                f"kit analysis returned an invalid ability for {name}"
            )
        ability_id = int(role["ability_id"])
        if ability_id in seen or supplied.get(ability_id) != role.get("ability"):
            raise GenerationError(f"kit analysis changed an ability for {name}")
        if any(
            not isinstance(role.get(field), str) or not role[field].strip()
            for field in ("tactical_role", "scaling_hooks")
        ):
            raise GenerationError(f"kit analysis omitted ability evidence for {name}")
        seen.add(ability_id)
        normalized_roles.append({
            "ability_id": ability_id,
            "ability": str(role["ability"]),
            "tactical_role": str(role["tactical_role"]).strip(),
            "scaling_hooks": str(role["scaling_hooks"]).strip(),
        })
    synergies = response.get("synergies")
    uncertainties = response.get("uncertainties")
    if seen != set(supplied):
        raise GenerationError(f"kit analysis omitted a supplied ability for {name}")
    if (
        not isinstance(synergies, list)
        or not synergies
        or any(not isinstance(value, str) or not value.strip() for value in synergies)
    ):
        raise GenerationError(f"kit analysis omitted supplied synergies for {name}")
    if not isinstance(uncertainties, list) or any(
        not isinstance(value, str) or not value.strip() for value in uncertainties
    ):
        raise GenerationError(f"kit analysis omitted supplied evidence for {name}")
    return {
        "hero_id": int(response["hero_id"]),
        "hero": name,
        "kit_basis_sha256": str(response["kit_basis_sha256"]),
        "prompt_version": KIT_PROMPT_VERSION,
        **{field: str(response[field]).strip() for field in text_fields},
        "ability_roles": normalized_roles,
        "synergies": [str(value).strip() for value in synergies],
        "uncertainties": [str(value).strip() for value in uncertainties],
    }


def _existing_entries(path: Path) -> dict[int, dict[str, Any]]:
    if not path.is_file():
        return {}
    heroes = _load_object(path).get("heroes")
    if not isinstance(heroes, list):
        return {}
    return {
        int(entry["hero_id"]): entry
        for entry in heroes
        if isinstance(entry, dict) and isinstance(entry.get("hero_id"), int)
    }


def validated_reusable_kit_profiles(
    existing: dict[int, dict[str, Any]],
    source_heroes: dict[int, dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    reusable: dict[int, dict[str, Any]] = {}
    for hero_id, entry in existing.items():
        hero = source_heroes.get(hero_id)
        if (
            hero is None
            or entry.get("prompt_version") != KIT_PROMPT_VERSION
            or entry.get("kit_basis_sha256") != hero.get("kit_basis_sha256")
        ):
            continue
        try:
            reusable[hero_id] = validate_kit_response(entry, hero)
        except GenerationError:
            continue
    return reusable


def run_codex(
    hero: dict[str, Any],
    *,
    schema_path: Path,
    model: str | None,
    prompt: str = PROMPT,
    timeout_seconds: float = 1200,
) -> dict[str, Any]:
    codex = shutil.which("codex")
    if not codex:
        raise GenerationError("codex executable was not found on PATH")
    command = [
        codex,
        "exec",
        "--ephemeral",
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "--ignore-user-config",
        "--ignore-rules",
        "--output-schema",
        str(schema_path.resolve()),
    ]
    if model:
        command.extend(["--model", model])
    command.append(prompt)
    with tempfile.TemporaryDirectory(prefix="deadlock-narrative-codex.") as workdir:
        try:
            result = subprocess.run(
                command,
                input=json.dumps(hero, ensure_ascii=False),
                text=True,
                cwd=workdir,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise GenerationError(
                f"Codex timed out generating {hero.get('hero')} after {timeout_seconds:g}s"
            ) from error
    if result.returncode != 0:
        raise GenerationError(
            f"Codex failed for {hero.get('hero')}:\n{result.stderr.strip()}"
        )
    try:
        response = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise GenerationError(
            f"Codex returned invalid JSON for {hero.get('hero')}: {result.stdout[:500]}"
        ) from error
    if not isinstance(response, dict):
        raise GenerationError(f"Codex returned a non-object for {hero.get('hero')}")
    return response


def _validate_complete_sentence(value: Any, label: str, hero_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value.rstrip()[-1] not in ".!?"
    ):
        raise GenerationError(f"Codex omitted a complete {label} for {hero_name}")
    return value.strip()


def _validate_prose_ceiling(text: str, hero_name: str) -> None:
    if ANALYTICS_LEAK_PATTERN.search(text):
        raise GenerationError(f"Codex leaked analytic-unit language for {hero_name}")
    if CAUSAL_PATTERN.search(text):
        raise GenerationError(f"Codex exceeded a non-causal claim for {hero_name}")


def validate_response(
    response: dict[str, Any],
    hero: dict[str, Any],
    *,
    require_context_match: bool = True,
) -> dict[str, Any]:
    """Admit prose only when it is an exact explanation of the closed policy.

    Returns:
        A normalized explanation whose identifiers and action set are unchanged.

    Raises:
        GenerationError: If prose changes policy identity, semantics, or claim strength.

    """
    hero_name = str(hero.get("hero") or hero.get("hero_id") or "unknown")
    identity_fields = (
        "hero_id",
        "snapshot_id",
        "policy_id",
        "narrative_basis_sha256",
    )
    if require_context_match:
        identity_fields = (*identity_fields, "context_sha256")
    for field in identity_fields:
        if response.get(field) != hero.get(field):
            raise GenerationError(f"Codex changed {field} for {hero_name}")
    tactical = response.get("tactical_profile")
    if not isinstance(tactical, dict):
        raise GenerationError(f"Codex omitted tactical_profile for {hero_name}")
    primary_role = tactical.get("primary_role")
    if not isinstance(primary_role, str) or not primary_role.strip():
        raise GenerationError(f"Codex omitted primary_role for {hero_name}")
    fight_role = _validate_complete_sentence(
        tactical.get("fight_role"), "fight role", hero_name
    )
    economy_plan = _validate_complete_sentence(
        tactical.get("economy_plan"), "economy plan", hero_name
    )
    ending = tactical.get("ending_duration_interpretation")
    source_ending = hero.get("ending_duration_profile")
    if not isinstance(ending, dict) or not isinstance(source_ending, dict):
        raise GenerationError(
            f"Codex omitted ending-duration interpretation for {hero_name}"
        )
    for field in ("estimand", "strongest_phase", "weakest_phase"):
        if ending.get(field) != source_ending.get(field):
            raise GenerationError(
                f"Codex changed ending-duration {field} for {hero_name}"
            )
    ending_plan = _validate_complete_sentence(
        ending.get("plan"), "ending-duration plan", hero_name
    )
    summary = _validate_complete_sentence(
        response.get("build_summary"), "build summary", hero_name
    )

    supplied_actions = hero.get("explainable_actions")
    explanations = response.get("action_explanations")
    if not isinstance(supplied_actions, list) or not isinstance(explanations, list):
        raise GenerationError(f"Codex omitted policy actions for {hero_name}")
    supplied_by_node = {
        str(action.get("node_id")): action
        for action in supplied_actions
        if isinstance(action, dict)
    }
    response_nodes = [
        str(explanation.get("node_id"))
        for explanation in explanations
        if isinstance(explanation, dict)
    ]
    if response_nodes != list(supplied_by_node) or len(response_nodes) != len(
        explanations
    ):
        raise GenerationError(f"Codex changed the closed action set for {hero_name}")
    normalized_actions = []
    for explanation in explanations:
        if not isinstance(explanation, dict):
            raise GenerationError(f"Codex returned a malformed action for {hero_name}")
        node_id = str(explanation["node_id"])
        supplied = supplied_by_node[node_id]
        if explanation.get("evidence_ref") != supplied.get("evidence_ref"):
            raise GenerationError(f"Codex changed evidence for action {node_id}")
        instruction = _validate_complete_sentence(
            explanation.get("instruction"), f"instruction for {node_id}", hero_name
        )
        if len(instruction.encode("utf-8")) > MAX_TACTICAL_INSTRUCTION_BYTES:
            raise GenerationError(
                f"Codex exceeded the {MAX_TACTICAL_INSTRUCTION_BYTES}-byte "
                f"instruction limit for {node_id}"
            )
        action_name = str(supplied.get("action") or "")
        if action_name and not _mentions_item(instruction, action_name):
            raise GenerationError(f"Codex omitted {action_name} from action {node_id}")
        if supplied.get("annotation") and CONDITION_PATTERN.search(instruction) is None:
            raise GenerationError(f"Codex removed the condition from action {node_id}")
        _validate_prose_ceiling(instruction, hero_name)
        normalized_actions.append({
            "node_id": node_id,
            "evidence_ref": str(explanation["evidence_ref"]),
            "instruction": instruction,
        })

    projection = hero.get("projection")
    categories = projection.get("categories") if isinstance(projection, dict) else None
    summaries = response.get("category_summaries")
    if not isinstance(categories, list) or not isinstance(summaries, list):
        raise GenerationError(f"Codex omitted projection categories for {hero_name}")
    supplied_names = [
        str(category.get("name"))
        for category in categories
        if isinstance(category, dict)
    ]
    response_names = [
        str(category.get("category"))
        for category in summaries
        if isinstance(category, dict)
    ]
    if response_names != supplied_names or len(response_names) != len(summaries):
        raise GenerationError(f"Codex changed projection categories for {hero_name}")
    all_items = {
        str(item.get("item"))
        for category in categories
        if isinstance(category, dict)
        for item in category.get("items") or []
        if isinstance(item, dict) and item.get("item")
    }
    normalized_categories = []
    for source_category, category in zip(categories, summaries, strict=True):
        if not isinstance(source_category, dict) or not isinstance(category, dict):
            raise GenerationError(
                f"Codex returned a malformed category for {hero_name}"
            )
        text = _validate_complete_sentence(
            category.get("summary"),
            f"category {source_category.get('name')}",
            hero_name,
        )
        raw_category_items = source_category.get("items")
        category_items = (
            {
                str(item.get("item"))
                for item in raw_category_items
                if isinstance(item, dict) and item.get("item")
            }
            if isinstance(raw_category_items, list)
            else set()
        )
        category_annotations = " ".join(
            str(action.get("annotation") or "")
            for action in supplied_actions
            if isinstance(action, dict)
            and str(action.get("action") or "") in category_items
        )
        allowed_replacement_refs = {
            item
            for item in all_items - category_items
            if _mentions_item(category_annotations, item)
        }
        mentioned = {item for item in all_items if _mentions_item(text, item)}
        if not mentioned or not mentioned <= (
            category_items | allowed_replacement_refs
        ):
            raise GenerationError(
                f"Codex used missing or cross-category items in {source_category.get('name')}"
            )
        if source_category.get("optional"):
            category_name = str(source_category.get("name") or "")
            if BUY_ALL_PATTERN.search(text) is not None:
                raise GenerationError(
                    f"Codex made {category_name} an automatic all-item purchase"
                )
            if category_name.startswith("TIER "):
                if REFERENCE_MENU_PATTERN.search(text) is None:
                    raise GenerationError(
                        f"Codex removed reference-menu semantics for {category_name}"
                    )
            elif CONDITION_PATTERN.search(text) is None:
                raise GenerationError(
                    f"Codex removed the optional trigger for {category_name}"
                )
        _validate_prose_ceiling(text, hero_name)
        normalized_categories.append({
            "category": str(category.get("category")),
            "summary": text,
        })
    combined = " ".join(
        [summary, fight_role, economy_plan, ending_plan]
        + [row["instruction"] for row in normalized_actions]
        + [row["summary"] for row in normalized_categories]
    )
    _validate_prose_ceiling(combined, hero_name)
    return {
        "hero_id": int(response["hero_id"]),
        "hero": hero_name,
        "snapshot_id": str(response["snapshot_id"]),
        "policy_id": str(response["policy_id"]),
        "context_sha256": str(hero.get("context_sha256")),
        "narrative_basis_sha256": str(response["narrative_basis_sha256"]),
        "prompt_version": PROMPT_VERSION,
        "tactical_profile": {
            "primary_role": primary_role.strip(),
            "fight_role": fight_role,
            "economy_plan": economy_plan,
            "ending_duration_interpretation": {
                "estimand": str(ending["estimand"]),
                "strongest_phase": str(ending["strongest_phase"]),
                "weakest_phase": str(ending["weakest_phase"]),
                "plan": ending_plan,
            },
        },
        "build_summary": summary,
        "action_explanations": normalized_actions,
        "category_summaries": normalized_categories,
    }


def _write_artifact(path: Path, document: dict[str, Any]) -> None:
    atomic_write_json(path, document)


def _artifact_document(
    source: dict[str, Any],
    generated: dict[int, dict[str, Any]],
    *,
    requested_hero_ids: set[int],
    kit_model: str | None,
    synthesis_model: str | None,
) -> dict[str, Any]:
    manifest = source["snapshot_manifest"]
    source_exclusions = source.get("exclusions")
    exclusions = [
        exclusion
        for exclusion in source_exclusions or []
        if isinstance(exclusion, dict)
        and exclusion.get("hero_id") in requested_hero_ids
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "generator": "codex exec (kit analysis + closed-policy explanation)",
        "prompt_version": PROMPT_VERSION,
        "models": {"kit_analysis": kit_model, "synthesis": synthesis_model},
        "source_context_sha256": source.get("source_context_sha256"),
        "snapshot_id": manifest.get("snapshot_id"),
        "patch": source.get("patch"),
        "cohort": {
            "client_version": manifest.get("client_version"),
            "match_mode": manifest.get("match_mode"),
            "game_mode": manifest.get("game_mode"),
            "rank_range": manifest.get("rank_range"),
            "as_of_timestamp": manifest.get("as_of_timestamp"),
        },
        "requested_hero_ids": sorted(requested_hero_ids),
        "exclusions": exclusions,
        "heroes": [
            generated[key] for key in sorted(generated) if key in requested_hero_ids
        ],
    }


def _kit_artifact_document(
    source: dict[str, Any],
    generated: dict[int, dict[str, Any]],
    *,
    model: str | None,
) -> dict[str, Any]:
    return {
        "schema_version": KIT_SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "generator": "codex exec",
        "prompt_version": KIT_PROMPT_VERSION,
        "model": model,
        "source_context_sha256": source.get("source_context_sha256"),
        "snapshot_manifest": source.get("snapshot_manifest"),
        "heroes": [generated[key] for key in sorted(generated)],
    }


def validated_reusable_entries(
    existing: dict[int, dict[str, Any]],
    source_heroes: dict[int, dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    """Return only exact-policy, exact-snapshot narrative artifacts.

    Returns:
        Revalidated entries keyed by hero ID.

    """
    reusable: dict[int, dict[str, Any]] = {}
    identity_fields = (
        "snapshot_id",
        "policy_id",
        "context_sha256",
        "narrative_basis_sha256",
    )
    for hero_id, entry in existing.items():
        hero = source_heroes.get(hero_id)
        if (
            hero is None
            or entry.get("prompt_version") not in REUSABLE_PROMPT_VERSIONS
            or any(entry.get(field) != hero.get(field) for field in identity_fields)
        ):
            continue
        try:
            reusable[hero_id] = validate_response(entry, hero)
        except GenerationError:
            continue
    return reusable


def main(argv: list[str] | None = None) -> int:
    args = parse_args() if argv is None else parse_args(argv)
    try:
        source = _load_object(args.input)
        try:
            validate_strategy_context_document(source)
        except StrategyContextError as error:
            raise GenerationError(str(error)) from error
        if not args.schema.is_file():
            raise GenerationError(f"response schema not found: {args.schema}")
        kit_schema = args.kit_schema
        if not kit_schema.is_file():
            raise GenerationError(f"kit response schema not found: {kit_schema}")
        kit_output = args.kit_output or args.output.with_name("kit-profiles.json")
        selected = _selected_heroes(source, args.hero)
        for hero in selected:
            validate_hero_context(hero)
        selected_ids = {int(hero["hero_id"]) for hero in selected}
        if args.hero is None:
            selected_ids.update(
                int(exclusion["hero_id"])
                for exclusion in source.get("exclusions") or []
                if isinstance(exclusion, dict)
                and isinstance(exclusion.get("hero_id"), int)
            )
        source_heroes = {int(hero["hero_id"]): hero for hero in selected}
        generated = validated_reusable_entries(
            _existing_entries(args.output),
            source_heroes,
        )
        kit_profiles = validated_reusable_kit_profiles(
            _existing_entries(kit_output),
            source_heroes,
        )
        for index, hero in enumerate(selected, start=1):
            hero_id = int(hero["hero_id"])
            if not args.force and hero_id in generated:
                print(
                    f"[{index}/{len(selected)}] reuse {hero.get('hero')}",
                    file=sys.stderr,
                )
                continue
            kit_profile = kit_profiles.get(hero_id)
            if args.force or kit_profile is None:
                print(
                    f"[{index}/{len(selected)}] Kit ({args.kit_model}): {hero.get('hero')}",
                    file=sys.stderr,
                )
                kit_profile = generate_validated_response(
                    kit_context(hero),
                    hero,
                    GenerationStage(
                        schema_path=kit_schema,
                        model=args.kit_model,
                        prompt=KIT_PROMPT,
                        identity_fields=("hero_id", "kit_basis_sha256"),
                        validator=validate_kit_response,
                        label=f"kit analysis for {hero.get('hero')}",
                        max_attempts=args.max_attempts,
                    ),
                )
                kit_profiles[hero_id] = kit_profile
                _write_artifact(
                    kit_output,
                    _kit_artifact_document(
                        source,
                        kit_profiles,
                        model=args.kit_model,
                    ),
                )
            print(
                f"[{index}/{len(selected)}] Synthesis ({args.model}): {hero.get('hero')}",
                file=sys.stderr,
            )
            model_context = synthesis_context(hero, kit_profile)
            generated[hero_id] = generate_validated_response(
                model_context,
                hero,
                GenerationStage(
                    schema_path=args.schema,
                    model=args.model,
                    prompt=PROMPT,
                    identity_fields=(
                        "hero_id",
                        "snapshot_id",
                        "policy_id",
                        "context_sha256",
                        "narrative_basis_sha256",
                    ),
                    validator=validate_response,
                    label=f"narrative synthesis for {hero.get('hero')}",
                    max_attempts=args.max_attempts,
                    normalizer=normalize_narrative_response,
                ),
            )
            _write_artifact(
                args.output,
                _artifact_document(
                    source,
                    generated,
                    requested_hero_ids=selected_ids,
                    kit_model=args.kit_model,
                    synthesis_model=args.model,
                ),
            )
        _write_artifact(
            kit_output,
            _kit_artifact_document(source, kit_profiles, model=args.kit_model),
        )
        _write_artifact(
            args.output,
            _artifact_document(
                source,
                generated,
                requested_hero_ids=selected_ids,
                kit_model=args.kit_model,
                synthesis_model=args.model,
            ),
        )
        print(f"Wrote {len(generated)} narrative(s): {args.output}")
        return 0
    except GenerationError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
