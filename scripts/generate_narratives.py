#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
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

from deadlock_build_sync.narratives import (
    DEFAULT_KIT_MODEL,
    DEFAULT_SYNTHESIS_MODEL,
)
from deadlock_build_sync.purchase_guide import MAX_ITEMS_PER_TIER
from deadlock_build_sync.strategy_context import (
    StrategyContextError,
    validate_strategy_context_document,
)

SCHEMA_VERSION = 2
PROMPT_VERSION = 15
REUSABLE_PROMPT_VERSIONS = frozenset({14, PROMPT_VERSION})
KIT_SCHEMA_VERSION = 1
KIT_PROMPT_VERSION = 1
QUARTERS = ("I", "II", "III", "IV")
COMPLETE_ABILITY_PATH_STEPS = 16
DEFAULT_GENERATION_ATTEMPTS = 3
DECISION_CONDITION_PATTERN = re.compile(
    r"\b(?:after|before|if|once|only|save|hold|until|when|while|unless|then)\b"
    r"|rather than|as soon as",
    re.IGNORECASE,
)
CHARGE_QUALIFICATION_PATTERN = re.compile(
    r"\b(?:ability\s*charges?\b(?!\s+up\b)|charged abilities\b"
    r"|allow(?:s|ed|ing)?\s+charges?\b)",
    re.IGNORECASE,
)
KIT_PROMPT = """
Role: Analyze one Deadlock hero kit from structured, patch-specific evidence.

Goal: Produce a compact tactical kit profile that a later synthesis model can
combine with independent item and match-duration analytics.

Success criteria:
- Use only hero_description, abilities, ability stats, and ability_path.
- Explain each supplied ability's tactical role and its explicit scaling hooks.
- Infer a grounded combat pattern, economy tendency, and scaling profile.
- Copy hero_id, kit_basis_sha256, ability IDs, and ability names exactly.
- Record uncertainty instead of inventing mechanics, numbers, combos, matchups,
  item interactions, or performance claims.

Constraints:
- The input intentionally contains no items or win-rate data.
- Treat ability descriptions and labeled stats as authoritative.
- Ability order shows timing emphasis, not causal proof of strength.

Output: Return only the schema-constrained JSON object.
""".strip()
PROMPT = """
You are writing an in-game Deadlock strategy description from one structured,
patch-specific hero context supplied as JSON on stdin.

Use only the supplied descriptions, item slots, analytics, and ability order.
Use general Deadlock tactical concepts to translate that evidence into a macro
plan, but treat the supplied context as authoritative for all hero and item
mechanics and numbers. Do not invent mechanics, numeric bonuses, combos,
matchups, or item co-purchase relationships.

Return the schema-constrained JSON object only.

The input may contain preliminary_kit_analysis produced by a smaller model from
the same supplied abilities and ability path. Use it as a planning aid, but
treat the raw hero, ability, item, and duration evidence as authoritative and
correct the preliminary analysis whenever it conflicts with that evidence.

First infer a tactical profile. Do not give every hero the same plan:
- Mobile control or burst kits may roam, gank, invade, or create picks.
- Durable close-range kits may pressure lane, initiate, frontline, or peel.
- Scaling weapon/spirit carries may prioritize lane and jungle farm, avoid
  low-value fights, and commit after a meaningful item/ability timing.
- Ranged pick heroes may hold long angles and punish isolated targets.
- Healing, rescue, and protection kits may escort pressure, counter-engage,
  sustain objectives, or stabilize allies.
- Split-push or objective pressure should appear only when supported.

tactical_profile:
- primary_role: a short, specific role such as `mobile control ganker`,
  `close-range initiator`, or `scaling backline carry`.
- fight_role: how this hero creates value in fights.
- economy_plan: whether and when this build should lane, jungle-farm, roam,
  gank, invade, pressure objectives, group, or avoid low-value fights.
- power_spikes: identify the single strongest spike and at most one genuinely
  distinct secondary spike. Each entry contains:
  - quarter: `I`, `II`, `III`, or `IV`.
  - trigger: the exact named core item or active plus the specific supplied
    ability unlock/final upgrade that align at this stage.
  - tactical_unlock: the new play this combination permits, such as starting
    ganks, surviving a committed dive, forcing an objective, or controlling a
    full teamfight. In one concise, complete sentence, state the selected item's
    documented contribution and the selected ability milestone's documented
    contribution before the resulting permission; neither component may be
    decorative or supported only by a different item or ability.
- Compare all four quarters before choosing. A spike must change what the hero
  can safely force. A completed active, expensive item, ultimate unlock, or
  final ability upgrade is not automatically a spike. Do not label ordinary
  damage, durability, or range growth as one. Include a secondary spike only
  when it opens a different macro or fight permission from the primary spike.
  Do not select a spectacular low-sample result over a stable high-volume core
  timing. Never infer causation from raw win rate.
- Make each trigger selection evidence-based. Choose exactly one primary item
  from that quarter's first three and one same-quarter ability milestone. Start
  with the lowest numeric rank_by_pick_rate as the high-volume default, then
  compare the first three items' raw outcomes and match counts, the selected
  complete ability path's outcome and volume, and the hero's broad duration
  curve. A higher item outcome is corroborating only when its sample is credible
  and its documented mechanics interact at that milestone; never select by raw
  win rate alone. A Tier III core can be a stronger supported breakpoint than a
  Tier IV core, so do not assume later tiers are monotonically stronger. Item
  purchase windows are net-worth ranges, not clock time, and the supplied path
  has no per-milestone outcome: do not invent a time mapping or attribute the
  path's outcome to one ability level. Put other supporting items or abilities
  in tactical_unlock instead of changing the trigger.
- When an item's supplied mechanics apply only to charged, imbued, or otherwise
  qualified abilities, pair it only with an ability whose supplied properties
  show that qualification. Two unrelated improvements in the same quarter are
  not an item-and-ability spike.
- duration_plan:
  - shape: copy duration_curve.shape exactly.
  - strongest_phase and weakest_phase: copy the corresponding supplied phase
    labels exactly.
  - macro_plan: explain whether the hero should accelerate and close, convert a
    midgame peak, scale patiently, or remain flexible.
  - late_build_response: `REINFORCE`, `COMPENSATE`, or `MIXED`.
  - response_reason: compare Tier III/IV core item mechanics with the natural
    duration curve. `REINFORCE` means the late items amplify a phase where the
    hero is already strong. `COMPENSATE` means survivability, access, control,
    reach, cleanse, or sustain directly covers a declining phase. Use `MIXED`
    when the package does both or merely preserves the hero's original threat.
- Duration results are observational and outcome-conditioned. Use broad,
  high-volume phase direction and the supplied tracked-game shares, not one
  noisy bucket. The 50m+ bucket is a rare tail: never let it define the curve
  alone, and mention it only when the adjacent 45–50m bucket supports the same
  direction. Never claim that duration or an item causes wins.
- Never tell a late-scaling hero to intentionally stall a winnable game. The
  supplied population shows that 45m+ is uncommon. Late scaling means the hero
  retains or gains relative leverage if the match naturally runs long; still
  convert clean picks, objectives, and ending opportunities at earlier spikes.
- This profile is review metadata and will not be copied into an item tier.

build_summary:
- 80–700 characters of concise plain text.
- Aim for 200–400 characters and finish with a complete sentence.
- Explain what the build revolves around, the hero's fight loop, how the
  ability descriptions interact with the leading item descriptions, and the
  max-order emphasis visible in the path.
- Name two to four genuinely build-defining items when their tactical purpose
  helps explain the resulting playstyle. Do not turn the summary into a list,
  reproduce item descriptions, enumerate stat lines, or mention analytics.
- State the hero's strongest tracked match-duration phase and whether the player
  should close before a decline, convert a midgame peak, or scale toward late
  fights. Do not include percentages or match counts.
- For a late-scaling hero, phrase the plan as retaining strength if the match
  runs late, never as a reason to delay an available close.

quarters I–IV:
- 60–600 characters each, plain text, no Markdown bullets.
- Aim for 180–350 characters and finish with a complete sentence.
- Treat I/II/III/IV as establish/accelerate/pressure/close.
- Use that quarter's corresponding four ability-order steps as context.
- Name at least one ability from those four steps in every quarter.
- Never name an ability before its first `UNLOCK` step. Once unlocked, an
  earlier-quarter ability may remain part of later instructions.
- Begin each string with `TIER I:`, `TIER II:`, `TIER III:`, or `TIER IV:`.
- For every quarter declared in tactical_profile.power_spikes, immediately
  follow the tier prefix with `POWER SPIKE —`, state the item-and-ability
  trigger, and explain the newly permitted play. Do not call every tier a
  power spike.
- In TIER III, connect the pressure plan to the hero's duration curve: force
  conversion if strength is already peaking, or preserve economy if the hero
  is still scaling. For `LATE_SCALING`, explicitly use an economy term such as
  `farm`, `economy`, or `preserve`; an ability's Spirit scaling does not satisfy
  this strategic requirement.
- In TIER IV, include `CURVE RESPONSE — REINFORCE`, `CURVE RESPONSE —
  COMPENSATE`, or `CURVE RESPONSE — MIXED` exactly as selected in
  tactical_profile.duration_plan. Explain how the named late items either
  amplify the hero's natural strength or cover a late weakness, and give the
  resulting close-out instructions.
- Give only concrete instructions for how to play the hero in that stage:
  positioning, engage pattern, ability sequencing, targets, resets, teamfight
  role, and when to commit or disengage.
- Every tier, including Tier IV, must state an explicit decision condition such
  as `when`, `after`, `if`, or `until` for committing, resetting, or closing.
  A sequence of commands without a condition is incomplete tactical advice.
- Name one to three items from the corresponding tier and explain why they
  change a tactical decision, power spike, target choice, ability sequence, or
  commit threshold. At least one must come from that tier's first three items.
  Do not merely tell the player to buy it or restate its description.
- If an active item appears among that tier's first three items, name it and
  give an explicit instruction for when to activate it, whom to target, where
  it fits before or after an ability, or which defensive/offensive moment to
  save it for. Never describe an active as a passive effect.
- You may refer to an earlier-tier item when it remains central to the current
  fight loop. Mention a lower-ranked active only as a situational alternative
  when its supplied mechanics clearly support the instruction.
- Each tier must choose a clear macro priority appropriate to this hero:
  pressure lane, farm lane/jungle, roam, gank, invade, look for a pick, group,
  force an objective, initiate, counter-engage, peel, split pressure, or reset.
  Do not force farming or ganking onto a hero whose evidence does not support it.
- Make the stage priority repeatable and explicit. Unless the supplied kit and
  build clearly require a different plan, anchor Tier I in lane/economy, Tier II
  in coordinated rotation and grouping, Tier III in objective pressure or
  conversion, and Tier IV in closing or ending. Add hero-specific tactics around
  that anchor instead of silently swapping the macro goal between equivalent
  alternatives.
- Use item purchase windows, path progression, pick rate, raw win rate, and
  match count silently to judge when the build is establishing, waiting for a
  power spike, or ready to pressure. Favor high-volume signals over spectacular
  low-sample win rates, and never claim an item causes wins.
- Use duration_curve.overall only as a silent baseline for the supplied early,
  mid, and late windows; never expose its raw rate in player-facing prose.
- Never mention an item slot, stat line, pick rate, win rate, match count,
  net-worth window, or the fact that context came from analytics.
- Item descriptions and stats are reasoning context. Translate them into
  concise tactical purpose; never copy them wholesale or dump their numbers.
- Make connections only where the supplied descriptions support them.

Copy hero_id, context_sha256, and narrative_basis_sha256 exactly from the input.
""".strip()


class GenerationError(RuntimeError):
    pass


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


def _mentions_upgrade(text: str, upgrade: str) -> bool:
    if upgrade == "UNLOCK":
        return re.search(r"\bunlock\w*\b", text, re.IGNORECASE) is not None
    return (
        re.search(
            rf"(?<!\w){re.escape(upgrade)}(?!\w)",
            text,
            re.IGNORECASE,
        )
        is not None
    )


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def bind_response_identity(
    response: dict[str, Any],
    source: dict[str, Any],
    fields: tuple[str, ...],
) -> dict[str, Any]:
    """Bind invocation-owned identity fields before semantic validation.

    Returns:
        A response copy containing the exact source identity values.

    """
    return {
        **response,
        **{field: source.get(field) for field in fields},
    }


def generate_validated_response(
    model_input: dict[str, Any],
    validation_context: dict[str, Any],
    stage: GenerationStage,
) -> dict[str, Any]:
    """Generate and validate one response with bounded retries.

    Returns:
        The first response that satisfies the production validator.

    Raises:
        GenerationError: If every generation or validation attempt fails.
        ValueError: If the configured attempt count is less than one.

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
                    f"retry {stage.label} "
                    f"({attempt + 1}/{stage.max_attempts}): {error}",
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
        A response copy with complete quarter and tactical-unlock sentences.

    """
    normalized = {**response}
    quarters = response.get("quarters")
    if isinstance(quarters, dict):
        normalized["quarters"] = {
            key: _finish_sentence(value) for key, value in quarters.items()
        }
    tactical_profile = response.get("tactical_profile")
    if isinstance(tactical_profile, dict):
        normalized_profile = {**tactical_profile}
        power_spikes = tactical_profile.get("power_spikes")
        if isinstance(power_spikes, list):
            normalized_profile["power_spikes"] = [
                {
                    **spike,
                    "tactical_unlock": _finish_sentence(spike.get("tactical_unlock")),
                }
                if isinstance(spike, dict)
                else spike
                for spike in power_spikes
            ]
        normalized["tactical_profile"] = normalized_profile
    return normalized


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate reviewed Deadlock build narratives with Codex."
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
        help=(
            "generation/validation attempts per model stage "
            f"(default: {DEFAULT_GENERATION_ATTEMPTS})"
        ),
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
    missing = (
        normalized
        - {str(hero.get("hero_id")) for hero in selected}
        - {str(hero.get("hero") or "").casefold().replace(" ", "") for hero in selected}
    )
    if missing:
        raise GenerationError(
            f"hero selector(s) not found: {', '.join(sorted(missing))}"
        )
    return selected


def validate_hero_context(hero: dict[str, Any]) -> None:
    """Reject a hero context that cannot support the production prompt.

    Raises:
        GenerationError: If required ability, item, or duration context is absent.

    """
    hero_name = str(hero.get("hero") or hero.get("hero_id") or "unknown")
    abilities = hero.get("abilities")
    if not isinstance(abilities, list) or len(abilities) != 4:
        raise GenerationError(f"strategy context omitted abilities for {hero_name}")

    ability_path = hero.get("ability_path")
    steps = ability_path.get("steps") if isinstance(ability_path, dict) else None
    if not isinstance(steps, list) or len(steps) != COMPLETE_ABILITY_PATH_STEPS:
        raise GenerationError(
            f"strategy context omitted a complete ability path for {hero_name}; "
            "run export-context again"
        )

    duration_curve = hero.get("duration_curve")
    if not isinstance(duration_curve, dict):
        raise GenerationError(
            f"strategy context omitted a complete duration curve for {hero_name}; "
            "run export-context again"
        )

    tiers = hero.get("tiers")
    if not isinstance(tiers, dict) or any(
        not isinstance(tiers.get(quarter), list)
        or len(tiers[quarter]) != MAX_ITEMS_PER_TIER
        for quarter in QUARTERS
    ):
        raise GenerationError(
            f"strategy context omitted complete item tiers for {hero_name}; "
            "run export-context again"
        )


def kit_context(hero: dict[str, Any]) -> dict[str, Any]:
    """Return the ability-only evidence made available to the kit model.

    Returns:
        A structured context without item or duration analytics.

    """
    ability_path = hero.get("ability_path")
    return {
        "hero_id": hero.get("hero_id"),
        "hero": hero.get("hero"),
        "hero_description": hero.get("hero_description"),
        "kit_basis_sha256": hero.get("kit_basis_sha256"),
        "abilities": hero.get("abilities"),
        "ability_path": (
            {
                "selection": ability_path.get("selection"),
                "steps": ability_path.get("steps"),
            }
            if isinstance(ability_path, dict)
            else None
        ),
    }


def validate_kit_response(
    response: dict[str, Any],
    hero: dict[str, Any],
) -> dict[str, Any]:
    """Validate and normalize one ability-only kit profile.

    Returns:
        The normalized profile with its prompt version.

    Raises:
        GenerationError: If the profile changes or omits supplied kit evidence.

    """
    hero_name = str(hero.get("hero") or hero.get("hero_id") or "unknown")
    if response.get("hero_id") != hero.get("hero_id"):
        raise GenerationError(f"kit analysis changed hero_id for {hero_name}")
    if response.get("kit_basis_sha256") != hero.get("kit_basis_sha256"):
        raise GenerationError(f"kit analysis changed kit_basis_sha256 for {hero_name}")

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
        raise GenerationError(
            f"kit analysis omitted its tactical profile for {hero_name}"
        )

    abilities = hero.get("abilities")
    supplied = (
        {
            int(ability["ability_id"]): str(ability.get("ability") or "")
            for ability in abilities
            if isinstance(ability, dict) and isinstance(ability.get("ability_id"), int)
        }
        if isinstance(abilities, list)
        else {}
    )
    ability_roles = response.get("ability_roles")
    if not isinstance(ability_roles, list) or len(ability_roles) != len(supplied):
        raise GenerationError(f"kit analysis omitted ability roles for {hero_name}")
    normalized_roles: list[dict[str, Any]] = []
    seen: set[int] = set()
    for role in ability_roles:
        if not isinstance(role, dict) or not isinstance(role.get("ability_id"), int):
            raise GenerationError(
                f"kit analysis returned an invalid ability for {hero_name}"
            )
        ability_id = int(role["ability_id"])
        if ability_id in seen or supplied.get(ability_id) != role.get("ability"):
            raise GenerationError(f"kit analysis changed an ability for {hero_name}")
        if any(
            not isinstance(role.get(field), str) or not role[field].strip()
            for field in ("tactical_role", "scaling_hooks")
        ):
            raise GenerationError(
                f"kit analysis omitted ability evidence for {hero_name}"
            )
        seen.add(ability_id)
        normalized_roles.append({
            "ability_id": ability_id,
            "ability": str(role["ability"]),
            "tactical_role": str(role["tactical_role"]).strip(),
            "scaling_hooks": str(role["scaling_hooks"]).strip(),
        })
    if seen != set(supplied):
        raise GenerationError(
            f"kit analysis omitted a supplied ability for {hero_name}"
        )

    synergies = response.get("synergies")
    uncertainties = response.get("uncertainties")
    if (
        not isinstance(synergies, list)
        or not synergies
        or any(not isinstance(value, str) or not value.strip() for value in synergies)
        or not isinstance(uncertainties, list)
        or any(
            not isinstance(value, str) or not value.strip() for value in uncertainties
        )
    ):
        raise GenerationError(
            f"kit analysis omitted synergies or uncertainty for {hero_name}"
        )

    return {
        "hero_id": int(response["hero_id"]),
        "hero": hero_name,
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
    document = _load_object(path)
    heroes = document.get("heroes")
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
    """Return kit profiles whose ability-only basis is still current.

    Returns:
        Valid profiles keyed by hero ID.

    """
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
                f"Codex timed out generating {hero.get('hero')} after "
                f"{timeout_seconds:g}s"
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


def validate_response(
    response: dict[str, Any],
    hero: dict[str, Any],
    *,
    require_context_match: bool = True,
) -> dict[str, Any]:
    if response.get("hero_id") != hero.get("hero_id"):
        raise GenerationError(f"Codex changed hero_id for {hero.get('hero')}")
    response_context_sha256 = response.get("context_sha256")
    if not _is_sha256(response_context_sha256):
        raise GenerationError(
            f"Codex returned an invalid context_sha256 for {hero.get('hero')}"
        )
    if require_context_match and response_context_sha256 != hero.get("context_sha256"):
        raise GenerationError(f"Codex changed context_sha256 for {hero.get('hero')}")
    response_basis_sha256 = response.get("narrative_basis_sha256")
    if not _is_sha256(response_basis_sha256):
        raise GenerationError(
            f"Codex returned an invalid narrative_basis_sha256 for {hero.get('hero')}"
        )
    if response_basis_sha256 != hero.get("narrative_basis_sha256"):
        raise GenerationError(
            f"Codex changed narrative_basis_sha256 for {hero.get('hero')}"
        )
    summary = response.get("build_summary")
    tactical_profile = response.get("tactical_profile")
    quarters = response.get("quarters")
    if not isinstance(tactical_profile, dict) or any(
        not isinstance(tactical_profile.get(field), str)
        or not tactical_profile[field].strip()
        for field in ("primary_role", "fight_role", "economy_plan")
    ):
        raise GenerationError(f"Codex omitted tactical_profile for {hero.get('hero')}")
    power_spikes = tactical_profile.get("power_spikes")
    if (
        not isinstance(power_spikes, list)
        or not 1 <= len(power_spikes) <= 2
        or any(
            not isinstance(spike, dict)
            or spike.get("quarter") not in QUARTERS
            or not isinstance(spike.get("trigger"), str)
            or not spike["trigger"].strip()
            or not isinstance(spike.get("tactical_unlock"), str)
            or not spike["tactical_unlock"].strip()
            for spike in power_spikes
        )
    ):
        raise GenerationError(
            f"Codex omitted valid power spikes for {hero.get('hero')}"
        )
    spike_quarters = [str(spike["quarter"]) for spike in power_spikes]
    if len(spike_quarters) != len(set(spike_quarters)):
        raise GenerationError(
            f"Codex repeated a power-spike quarter for {hero.get('hero')}"
        )
    duration_curve = hero.get("duration_curve")
    duration_plan = tactical_profile.get("duration_plan")
    if (
        not isinstance(duration_curve, dict)
        or not isinstance(duration_plan, dict)
        or any(
            not isinstance(duration_plan.get(field), str)
            or not duration_plan[field].strip()
            for field in (
                "shape",
                "strongest_phase",
                "weakest_phase",
                "macro_plan",
                "late_build_response",
                "response_reason",
            )
        )
    ):
        raise GenerationError(f"Codex omitted a duration plan for {hero.get('hero')}")
    if duration_plan["shape"] != duration_curve.get("shape"):
        raise GenerationError(
            f"Codex changed the duration-curve shape for {hero.get('hero')}"
        )
    if duration_plan["strongest_phase"] != duration_curve.get("strongest_phase"):
        raise GenerationError(
            f"Codex changed the strongest duration phase for {hero.get('hero')}"
        )
    if duration_plan["weakest_phase"] != duration_curve.get("weakest_phase"):
        raise GenerationError(
            f"Codex changed the weakest duration phase for {hero.get('hero')}"
        )
    if duration_plan["late_build_response"] not in {
        "REINFORCE",
        "COMPENSATE",
        "MIXED",
    }:
        raise GenerationError(
            f"Codex returned an invalid late-build response for {hero.get('hero')}"
        )
    if not isinstance(summary, str) or not summary.strip():
        raise GenerationError(f"Codex omitted build_summary for {hero.get('hero')}")
    if not isinstance(quarters, dict) or any(
        not isinstance(quarters.get(quarter), str) or not quarters[quarter].strip()
        for quarter in QUARTERS
    ):
        raise GenerationError(f"Codex omitted a quarter for {hero.get('hero')}")
    for quarter in QUARTERS:
        if not quarters[quarter].lstrip().startswith(f"TIER {quarter}:"):
            raise GenerationError(
                f"Codex did not label tier {quarter} for {hero.get('hero')}"
            )
        if quarters[quarter].rstrip()[-1] not in ".!?":
            raise GenerationError(
                f"Codex did not finish tier {quarter} for {hero.get('hero')}"
            )
        if DECISION_CONDITION_PATTERN.search(quarters[quarter]) is None:
            raise GenerationError(
                f"Codex omitted a decision condition in tier {quarter} for "
                f"{hero.get('hero')}"
            )
        if quarter in spike_quarters and "POWER SPIKE" not in quarters[quarter]:
            raise GenerationError(
                f"Codex did not expose the tier {quarter} power spike for "
                f"{hero.get('hero')}"
            )
    if (
        duration_curve.get("shape") == "LATE_SCALING"
        and re.search(
            r"\b(?:economy|farm|patient|preserve)\w*\b",
            quarters["III"],
            re.IGNORECASE,
        )
        is None
    ):
        raise GenerationError(
            f"Codex did not preserve economy in tier III for {hero.get('hero')}"
        )
    expected_curve_label = f"CURVE RESPONSE — {duration_plan['late_build_response']}"
    if expected_curve_label not in quarters["IV"]:
        raise GenerationError(
            f"Codex did not expose the Tier IV curve response for {hero.get('hero')}"
        )

    tiers = hero.get("tiers")
    if not isinstance(tiers, dict):
        raise GenerationError(f"context omitted item tiers for {hero.get('hero')}")
    active_verbs = re.compile(
        r"\b(?:activate|cast|hold|press|save|target|trigger|use)\b",
        re.IGNORECASE,
    )
    supplied_items = [
        item
        for items in tiers.values()
        if isinstance(items, list)
        for item in items
        if isinstance(item, dict) and str(item.get("item") or "").strip()
    ]
    supplied_item_names = [str(item["item"]).strip() for item in supplied_items]
    supplied_abilities = [
        ability
        for ability in hero.get("abilities") or []
        if isinstance(ability, dict) and str(ability.get("ability") or "").strip()
    ]
    supplied_ability_names = [
        str(ability["ability"]).strip() for ability in supplied_abilities
    ]
    ability_path = hero.get("ability_path")
    ability_steps = (
        ability_path.get("steps") if isinstance(ability_path, dict) else None
    )
    path_steps = (
        [step for step in ability_steps if isinstance(step, dict)]
        if isinstance(ability_steps, list)
        else []
    )
    first_ability_quarters: dict[str, int] = {}
    for step in path_steps:
        ability = step.get("ability")
        quarter = step.get("quarter")
        if not isinstance(ability, str) or not isinstance(quarter, int):
            continue
        first_ability_quarters[ability] = min(
            quarter,
            first_ability_quarters.get(ability, quarter),
        )
    for spike in power_spikes:
        quarter = str(spike["quarter"])
        trigger = str(spike["trigger"])
        tactical_unlock = str(spike["tactical_unlock"])
        if tactical_unlock.rstrip()[-1] not in ".!?":
            raise GenerationError(
                f"Codex did not finish its tactical unlock for {hero.get('hero')}"
            )
        mentioned_items = [
            item for item in supplied_item_names if _mentions_item(trigger, item)
        ]
        core_items = tiers.get(quarter)
        core_item_names = (
            [
                str(item.get("item") or "").strip()
                for item in core_items[:3]
                if isinstance(item, dict) and str(item.get("item") or "").strip()
            ]
            if isinstance(core_items, list)
            else []
        )
        if len(mentioned_items) != 1 or mentioned_items[0] not in core_item_names:
            raise GenerationError(
                "Codex power-spike trigger must name exactly one top-three "
                f"same-tier item for {hero.get('hero')}"
            )
        mentioned_abilities = [
            ability
            for ability in supplied_ability_names
            if _mentions_item(trigger, ability)
        ]
        if len(mentioned_abilities) != 1:
            raise GenerationError(
                "Codex power-spike trigger must name exactly one supplied ability "
                f"for {hero.get('hero')}"
            )
        selected_item = next(
            item
            for item in supplied_items
            if str(item["item"]).strip() == mentioned_items[0]
        )
        selected_ability = next(
            ability
            for ability in supplied_abilities
            if str(ability["ability"]).strip() == mentioned_abilities[0]
        )
        if CHARGE_QUALIFICATION_PATTERN.search(_context_text(selected_item)) and not (
            CHARGE_QUALIFICATION_PATTERN.search(_context_text(selected_ability))
        ):
            raise GenerationError(
                "Codex paired a charge-specific item with an ability whose supplied "
                f"mechanics do not show charges for {hero.get('hero')}"
            )
        if path_steps:
            matching_steps = [
                step
                for step in path_steps
                if step.get("quarter") == QUARTERS.index(quarter) + 1
                and step.get("ability") == mentioned_abilities[0]
                and isinstance(step.get("upgrade"), str)
                and _mentions_upgrade(trigger, str(step["upgrade"]))
            ]
            if len(matching_steps) != 1:
                raise GenerationError(
                    "Codex power-spike trigger must name one real same-tier "
                    f"ability milestone for {hero.get('hero')}"
                )
    for quarter in QUARTERS:
        quarter_number = QUARTERS.index(quarter) + 1
        quarter_abilities = {
            str(step["ability"]).strip()
            for step in path_steps
            if step.get("quarter") == quarter_number
            and isinstance(step.get("ability"), str)
            and str(step["ability"]).strip()
        }
        if quarter_abilities and not any(
            _mentions_item(quarters[quarter], ability) for ability in quarter_abilities
        ):
            raise GenerationError(
                f"Codex omitted a tier {quarter} ability-path ability for "
                f"{hero.get('hero')}"
            )
        future_abilities = [
            ability
            for ability, first_quarter in first_ability_quarters.items()
            if first_quarter > quarter_number
            and _mentions_item(quarters[quarter], ability)
        ]
        if future_abilities:
            raise GenerationError(
                f"Codex mentioned future ability(s) in tier {quarter} for "
                f"{hero.get('hero')}: {', '.join(sorted(future_abilities))}"
            )

        items = tiers.get(quarter)
        if not isinstance(items, list):
            raise GenerationError(
                f"context omitted tier {quarter} items for {hero.get('hero')}"
            )
        core_items = [
            item
            for item in items[:3]
            if isinstance(item, dict) and str(item.get("item") or "").strip()
        ]
        named_core_items = [
            str(item["item"])
            for item in core_items
            if _mentions_item(quarters[quarter], str(item["item"]))
        ]
        if not named_core_items:
            raise GenerationError(
                f"Codex did not explain a core tier {quarter} item for "
                f"{hero.get('hero')}"
            )
        active_core_items = [
            str(item["item"]) for item in core_items if item.get("is_active_item")
        ]
        missing_actives = [
            item
            for item in active_core_items
            if not _mentions_item(quarters[quarter], item)
        ]
        if missing_actives:
            raise GenerationError(
                f"Codex omitted core active item(s) in tier {quarter} for "
                f"{hero.get('hero')}: {', '.join(missing_actives)}"
            )
        if active_core_items and active_verbs.search(quarters[quarter]) is None:
            raise GenerationError(
                f"Codex did not give an activation instruction in tier {quarter} "
                f"for {hero.get('hero')}"
            )

    combined = " ".join([summary, *[quarters[quarter] for quarter in QUARTERS]])
    normalized = combined.casefold()
    banned_phrases = ("pick rate", "win rate", "match count", "net worth")
    leaked_phrases = [phrase for phrase in banned_phrases if phrase in normalized]
    if leaked_phrases:
        raise GenerationError(
            f"Codex leaked analytics language for {hero.get('hero')}: "
            f"{', '.join(leaked_phrases)}"
        )
    return {
        "hero_id": int(response["hero_id"]),
        "hero": str(hero.get("hero") or response["hero_id"]),
        "context_sha256": response_context_sha256,
        "narrative_basis_sha256": response_basis_sha256,
        "prompt_version": PROMPT_VERSION,
        "tactical_profile": {
            **{
                field: tactical_profile[field].strip()
                for field in ("primary_role", "fight_role", "economy_plan")
            },
            "power_spikes": sorted(
                [
                    {
                        "quarter": str(spike["quarter"]),
                        "trigger": str(spike["trigger"]).strip(),
                        "tactical_unlock": str(spike["tactical_unlock"]).strip(),
                    }
                    for spike in power_spikes
                ],
                key=lambda spike: QUARTERS.index(spike["quarter"]),
            ),
            "duration_plan": {
                field: duration_plan[field].strip()
                for field in (
                    "shape",
                    "strongest_phase",
                    "weakest_phase",
                    "macro_plan",
                    "late_build_response",
                    "response_reason",
                )
            },
        },
        "build_summary": summary.strip(),
        "quarters": {quarter: quarters[quarter].strip() for quarter in QUARTERS},
    }


def _write_artifact(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as output:
            json.dump(document, output, indent=2, ensure_ascii=False)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
            temporary = Path(output.name)
        temporary.replace(path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _artifact_document(
    source: dict[str, Any],
    generated: dict[int, dict[str, Any]],
    *,
    kit_model: str | None,
    synthesis_model: str | None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "generator": "codex exec (kit analysis + synthesis)",
        "prompt_version": PROMPT_VERSION,
        "models": {
            "kit_analysis": kit_model,
            "synthesis": synthesis_model,
        },
        "source_context_sha256": source.get("source_context_sha256"),
        "patch": source.get("patch"),
        "heroes": [generated[key] for key in sorted(generated)],
    }


def _kit_artifact_document(
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
        "heroes": [generated[key] for key in sorted(generated)],
    }


def validated_reusable_entries(
    existing: dict[int, dict[str, Any]],
    source_heroes: dict[int, dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    reusable: dict[int, dict[str, Any]] = {}
    for hero_id, entry in existing.items():
        hero = source_heroes.get(hero_id)
        if (
            hero is None
            # Version 15 adds an ability-unlock timing rule. Version 14 output
            # is safe to migrate only when it passes the stricter validator.
            or entry.get("prompt_version") not in REUSABLE_PROMPT_VERSIONS
            or entry.get("narrative_basis_sha256") != hero.get("narrative_basis_sha256")
        ):
            continue
        try:
            reusable[hero_id] = validate_response(
                entry,
                hero,
                require_context_match=False,
            )
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
        kit_schema = getattr(
            args,
            "kit_schema",
            Path(__file__).resolve().parents[1]
            / "schemas/kit-analysis-response.schema.json",
        )
        if not kit_schema.is_file():
            raise GenerationError(f"kit response schema not found: {kit_schema}")
        kit_output = getattr(args, "kit_output", None) or args.output.with_name(
            "kit-profiles.json"
        )
        kit_model = getattr(args, "kit_model", DEFAULT_KIT_MODEL)
        synthesis_model = args.model or DEFAULT_SYNTHESIS_MODEL
        selected = _selected_heroes(source, args.hero)
        for hero in selected:
            validate_hero_context(hero)
        existing = _existing_entries(args.output)
        source_heroes: dict[int, dict[str, Any]] = {}
        for hero in source["heroes"]:
            if not isinstance(hero.get("hero_id"), int):
                continue
            try:
                validate_hero_context(hero)
            except GenerationError:
                continue
            source_heroes[int(hero["hero_id"])] = hero
        generated = validated_reusable_entries(existing, source_heroes)
        kit_profiles = validated_reusable_kit_profiles(
            _existing_entries(kit_output),
            source_heroes,
        )
        artifact_written = False
        kit_artifact_written = False
        for index, hero in enumerate(selected, start=1):
            hero_id = int(hero["hero_id"])
            reusable = generated.get(hero_id)
            if not args.force and reusable is not None:
                print(
                    f"[{index}/{len(selected)}] reuse {hero.get('hero')}",
                    file=sys.stderr,
                )
                generated[hero_id] = reusable
                continue
            kit_profile = kit_profiles.get(hero_id)
            if args.force or kit_profile is None:
                print(
                    f"[{index}/{len(selected)}] Kit ({kit_model}): {hero.get('hero')}",
                    file=sys.stderr,
                )
                kit_profile = generate_validated_response(
                    kit_context(hero),
                    hero,
                    GenerationStage(
                        schema_path=kit_schema,
                        model=kit_model,
                        prompt=KIT_PROMPT,
                        identity_fields=("hero_id", "kit_basis_sha256"),
                        validator=validate_kit_response,
                        label=f"kit analysis for {hero.get('hero')}",
                        max_attempts=getattr(
                            args,
                            "max_attempts",
                            DEFAULT_GENERATION_ATTEMPTS,
                        ),
                    ),
                )
                kit_profiles[hero_id] = kit_profile
                _write_artifact(
                    kit_output,
                    _kit_artifact_document(kit_profiles, model=kit_model),
                )
                kit_artifact_written = True
            else:
                print(
                    f"[{index}/{len(selected)}] reuse kit: {hero.get('hero')}",
                    file=sys.stderr,
                )
            print(
                f"[{index}/{len(selected)}] Synthesis ({synthesis_model}): "
                f"{hero.get('hero')}",
                file=sys.stderr,
            )
            synthesis_context = {
                **hero,
                "preliminary_kit_analysis": kit_profile,
            }
            generated[hero_id] = generate_validated_response(
                synthesis_context,
                synthesis_context,
                GenerationStage(
                    schema_path=args.schema,
                    model=synthesis_model,
                    prompt=PROMPT,
                    identity_fields=(
                        "hero_id",
                        "context_sha256",
                        "narrative_basis_sha256",
                    ),
                    validator=validate_response,
                    label=f"narrative synthesis for {hero.get('hero')}",
                    max_attempts=getattr(
                        args,
                        "max_attempts",
                        DEFAULT_GENERATION_ATTEMPTS,
                    ),
                    normalizer=normalize_narrative_response,
                ),
            )
            _write_artifact(
                args.output,
                _artifact_document(
                    source,
                    generated,
                    kit_model=kit_model,
                    synthesis_model=synthesis_model,
                ),
            )
            artifact_written = True
        if kit_profiles and not kit_artifact_written:
            _write_artifact(
                kit_output,
                _kit_artifact_document(kit_profiles, model=kit_model),
            )
        if not artifact_written:
            _write_artifact(
                args.output,
                _artifact_document(
                    source,
                    generated,
                    kit_model=kit_model,
                    synthesis_model=synthesis_model,
                ),
            )
        print(f"Wrote {len(generated)} narrative(s): {args.output}")
        return 0
    except GenerationError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
