#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Callable

from deadlock_build_sync.artifacts import atomic_write_json
from deadlock_build_sync.build_evidence import THREAT_CLASSES
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

_KitAbilityRole = dict[str, Any]
_ProjectionCategory = dict[str, Any]
type BuildKey = tuple[int, str]

SCHEMA_VERSION = NARRATIVE_SCHEMA_VERSION
PROMPT_VERSION = NARRATIVE_PROMPT_VERSION
REUSABLE_PROMPT_VERSIONS = frozenset({PROMPT_VERSION})
KIT_SCHEMA_VERSION = 2
KIT_PROMPT_VERSION = 5
DEFAULT_GENERATION_ATTEMPTS = 3
DEFAULT_GENERATION_CONCURRENCY = 8
DEFAULT_RATE_LIMIT_BACKOFF_SECONDS = 1.0
MAX_RATE_LIMIT_BACKOFF_SECONDS = 60.0
CONDITION_PATTERN = re.compile(
    r"\b(?:after|before|if|once|only|save|hold|until|when|while|unless|then)\b"
    r"|rather than|as soon as",
    re.IGNORECASE,
)
TRIGGER_PATTERN = re.compile(r"\b(?:if|when)\b", re.IGNORECASE)
REFERENCE_MENU_PATTERN = re.compile(
    r"\b(?:adapt|menu|option|reference|situational)\w*\b", re.IGNORECASE
)
BUY_ALL_PATTERN = re.compile(
    r"\b(?:buy|get|purchase|take)\s+(?:all|every)\b", re.IGNORECASE
)
CHOICE_PATTERN = re.compile(r"\b(?:choose|instead|replace)\b|\bover\b", re.IGNORECASE)
EXECUTION_PATTERN = re.compile(
    r"\b(?:use|activate|apply|hold|trigger)\b", re.IGNORECASE
)
FAILURE_PATTERN = re.compile(r"\b(?:skip|avoid|unless|fails?|do not)\b", re.IGNORECASE)
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
CORRUPT_PROSE_PATTERN = re.compile(
    r"[\u200b-\u200f\u202a-\u202e\u2060-\u206f\u4e00-\u9fff]"
    r"|(?<=[A-Za-z])\d+(?=\W|$)"
)
RATE_LIMIT_PATTERN = re.compile(
    r"\b(?:429|rate[ -]?limit(?:ed|ing)?|too many requests)\b",
    re.IGNORECASE,
)
RETRY_AFTER_PATTERN = re.compile(
    r"(?:retry[ -]?after|try again in)\s*(?::|=)?\s*"
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>milliseconds?|ms|seconds?|s)?",
    re.IGNORECASE,
)

KIT_PROMPT = """
Role: explain one Deadlock hero kit from a closed, patch-specific mechanics packet.

Use only hero_mechanics and ability_policy. The hero description and abilities are
nested in hero_mechanics. Preserve all supplied IDs and names. Explain each
ability's tactical role and explicit scaling hooks. Treat the reached-state ability
policy as a descriptive default, not proof that one universal order is optimal.
Record uncertainty instead of inventing mechanics, numeric effects, combos,
matchups, or item interactions.

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
- Copy hero_id, path_id, snapshot_id, policy_id, context_sha256, and
  narrative_basis_sha256 exactly.
- Use only supplied mechanics and preliminary_kit_analysis. Never invent a
  mechanic, numeric effect, combo, matchup, timing, target, or causal benefit.
- A descriptive association may be called observed or associated only. Never
  claim an item causes wins or improves win probability.
- Never use cause, causes, caused, guarantee, or guarantees anywhere in the
  prose, including when paraphrasing a supplied mechanic. Use neutral mechanic
  verbs such as triggers, applies, deals, grants, or reduces instead.
- ending_duration_profile describes outcomes among games ending in each phase;
  it is not a live power curve and is not permission to stall a winnable game.
  When both phase labels are UNAVAILABLE, state that the cohort is unsupported
  and make no phase-strength claim.
- Price tiers are price tiers. They are not early/mid/late phases and are never
  paired with equal quarters of the ability order.

tactical_profile:
- Give a hero-specific role, fight role, and economy plan grounded in the kit.
- Make primary_role one complete sentence of at most 100 characters.
- Copy the ending-duration estimand and strongest/weakest phase labels exactly.
  Explain a conservative conversion plan without exposing rates or counts, or
  acknowledge the explicit unavailable state without inventing a phase.

build_summary:
- In 80–700 plain-text characters, describe the invariant role, supported CORE
  path, and the purpose of the four tier reference menus. Do not dump stats or
  analytics language.

action_explanations:
- Return every supplied explainable action exactly once, in supplied order.
- The output array length must equal the input explainable_actions length. The
  nth output must copy the nth input's node_id and evidence_ref; never merge,
  summarize, skip, or duplicate actions, even when several actions look similar.
- Copy node_id and evidence_ref. The instruction must name that supplied action.
- Keep every instruction within 165 UTF-8 bytes so the deterministic timing line
  can fit in the Steam hover.
- Explain only the supplied annotation/mechanics and stay within the claim's
  language ceiling. Conditional actions must retain their trigger, replacement,
  execution, and failure condition.

category_summaries:
- Return every supplied projection category exactly once, in supplied order.
- Copy the category name. Each summary must name at least one item from that
  category exactly as supplied and must not name any item from another category,
  even as a comparison.
- CORE ITEMS is the automatic Queue. OPTIONAL CORE and TIER 1–4 never enter it.
  OPTIONAL CORE contains supported final-slot swaps: preserve the supplied trigger,
  replacement, execution, and failure condition without claiming causal benefit.
  Tier rows are optional reference menus:
  describe candidates conservatively and say to choose one situationally. Never
  describe a tier menu as a combined purchase or claim adoption proves a
  counter/trigger. Do not write "buy all", "buy every", "get all", "get every",
  "purchase all", or "purchase every", including in a negated sentence.
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


class _RequestLimiter:
    """Bound concurrent Codex calls and coordinate rate-limit backpressure."""

    def __init__(self, max_concurrency: int) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least one")
        self._max_concurrency = max_concurrency
        self._current_limit = max_concurrency
        self._in_flight = 0
        self._not_before = 0.0
        self._successful_requests = 0
        self._condition = threading.Condition()

    @property
    def current_limit(self) -> int:
        with self._condition:
            return self._current_limit

    def acquire(self) -> None:
        with self._condition:
            while True:
                delay = self._not_before - time.monotonic()
                if self._in_flight < self._current_limit and delay <= 0:
                    self._in_flight += 1
                    return
                self._condition.wait(timeout=delay if delay > 0 else None)

    def release(
        self,
        error: GenerationError | None,
        *,
        attempt: int,
    ) -> float:
        """Release one request and return any local retry delay.

        Returns:
            Seconds the affected pipeline should wait before a local retry.

        Raises:
            RuntimeError: If no request slot is currently held.

        """
        with self._condition:
            if self._in_flight < 1:
                raise RuntimeError("cannot release a request that was not acquired")
            self._in_flight -= 1
            delay = self._release_delay(error, attempt=attempt)
            self._condition.notify_all()
            return delay

    def _release_delay(
        self,
        error: GenerationError | None,
        *,
        attempt: int,
    ) -> float:
        if error is None:
            self._record_successful_request()
            return 0.0
        if not _is_rate_limit_error(error):
            return random.uniform(  # ruff: ignore[suspicious-non-cryptographic-random-usage]
                0.05,
                min(0.5, 0.1 * attempt),
            )
        return self._record_rate_limit(error, attempt=attempt)

    def _record_successful_request(self) -> None:
        if (
            self._current_limit >= self._max_concurrency
            or time.monotonic() < self._not_before
        ):
            return
        self._successful_requests += 1
        if self._successful_requests >= self._current_limit:
            self._current_limit += 1
            self._successful_requests = 0

    def _record_rate_limit(self, error: GenerationError, *, attempt: int) -> float:
        supplied_delay = _retry_after_seconds(error)
        base_delay = (
            supplied_delay
            if supplied_delay is not None
            else min(
                DEFAULT_RATE_LIMIT_BACKOFF_SECONDS * (2 ** (attempt - 1)),
                MAX_RATE_LIMIT_BACKOFF_SECONDS,
            )
        )
        jitter_ceiling = min(1.0, max(0.1, base_delay * 0.25))
        delay = base_delay + random.uniform(  # ruff: ignore[suspicious-non-cryptographic-random-usage]
            0.0,
            jitter_ceiling,
        )
        self._not_before = max(self._not_before, time.monotonic() + delay)
        self._current_limit = max(1, self._current_limit // 2)
        self._successful_requests = 0
        return delay


def _is_rate_limit_error(error: GenerationError) -> bool:
    return RATE_LIMIT_PATTERN.search(str(error)) is not None


def _retry_after_seconds(error: GenerationError) -> float | None:
    match = RETRY_AFTER_PATTERN.search(str(error))
    if match is None:
        return None
    delay = float(match.group("value"))
    unit = (match.group("unit") or "seconds").casefold()
    return delay / 1000 if unit.startswith("m") else delay


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


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


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


def bind_response_structure(
    response: dict[str, Any],
    source: dict[str, Any],
) -> dict[str, Any]:
    """Restore positional policy identities without repairing structural omissions.

    Returns:
        A shallow response copy with source-owned row identities restored when the
        model preserved exact array cardinality.

    """
    bound = {**response}
    response_actions = response.get("action_explanations")
    source_actions = source.get("explainable_actions")
    if (
        isinstance(response_actions, list)
        and isinstance(source_actions, list)
        and len(response_actions) == len(source_actions)
        and all(isinstance(row, dict) for row in response_actions)
        and all(isinstance(row, dict) for row in source_actions)
    ):
        bound["action_explanations"] = [
            {
                **response_row,
                "node_id": source_row.get("node_id"),
                "evidence_ref": source_row.get("evidence_ref"),
            }
            for response_row, source_row in zip(
                [row for row in response_actions if isinstance(row, dict)],
                [row for row in source_actions if isinstance(row, dict)],
                strict=True,
            )
        ]
    response_categories = response.get("category_summaries")
    projection = source.get("projection")
    source_categories = (
        projection.get("categories") if isinstance(projection, dict) else None
    )
    if (
        isinstance(response_categories, list)
        and isinstance(source_categories, list)
        and len(response_categories) == len(source_categories)
        and all(isinstance(row, dict) for row in response_categories)
        and all(isinstance(row, dict) for row in source_categories)
    ):
        bound["category_summaries"] = [
            {**response_row, "category": source_row.get("name")}
            for response_row, source_row in zip(
                [row for row in response_categories if isinstance(row, dict)],
                [row for row in source_categories if isinstance(row, dict)],
                strict=True,
            )
        ]
    return bound


@dataclass(frozen=True)
class _GenerationRequestResult:
    response: dict[str, Any]
    error: GenerationError | None
    retry_delay: float


def _request_codex_response(
    model_input: dict[str, Any],
    stage: GenerationStage,
    request_limiter: _RequestLimiter,
    *,
    attempt: int,
) -> _GenerationRequestResult:
    request_limiter.acquire()
    request_error: GenerationError | None = None
    response: dict[str, Any] = {}
    try:
        response = run_codex(
            model_input,
            schema_path=stage.schema_path,
            model=stage.model,
            prompt=stage.prompt,
            timeout_seconds=stage.timeout_seconds,
        )
    except GenerationError as error:
        request_error = error
    finally:
        retry_delay = request_limiter.release(request_error, attempt=attempt)
    return _GenerationRequestResult(response, request_error, retry_delay)


def _admit_generated_response(
    response: dict[str, Any],
    validation_context: dict[str, Any],
    stage: GenerationStage,
) -> dict[str, Any]:
    bound_response = bind_response_identity(
        response,
        validation_context,
        stage.identity_fields,
    )
    bound_response = bind_response_structure(bound_response, validation_context)
    if stage.normalizer is not None:
        bound_response = stage.normalizer(bound_response)
    return stage.validator(bound_response, validation_context)


def _retry_failed_codex_request(
    stage: GenerationStage,
    error: GenerationError,
    *,
    attempt: int,
    retry_delay: float,
) -> None:
    if attempt >= stage.max_attempts:
        return
    print(
        f"retry {stage.label} ({attempt + 1}/{stage.max_attempts}) "
        f"after {retry_delay:.2f}s: {error}",
        file=sys.stderr,
    )
    if not _is_rate_limit_error(error):
        time.sleep(retry_delay)


def _retry_rejected_response(
    stage: GenerationStage,
    error: GenerationError,
    *,
    attempt: int,
) -> None:
    if attempt >= stage.max_attempts:
        return
    retry_delay = random.uniform(  # ruff: ignore[suspicious-non-cryptographic-random-usage]
        0.05,
        min(0.5, 0.1 * attempt),
    )
    print(
        f"retry {stage.label} ({attempt + 1}/{stage.max_attempts}) "
        f"after {retry_delay:.2f}s: {error}",
        file=sys.stderr,
    )
    time.sleep(retry_delay)


def generate_validated_response(
    model_input: dict[str, Any],
    validation_context: dict[str, Any],
    stage: GenerationStage,
    *,
    request_limiter: _RequestLimiter | None = None,
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
    limiter = request_limiter or _RequestLimiter(1)
    last_error: GenerationError | None = None
    for attempt in range(1, stage.max_attempts + 1):
        request = _request_codex_response(
            model_input,
            stage,
            limiter,
            attempt=attempt,
        )
        if request.error is not None:
            last_error = request.error
            _retry_failed_codex_request(
                stage,
                request.error,
                attempt=attempt,
                retry_delay=request.retry_delay,
            )
            continue
        try:
            return _admit_generated_response(
                request.response,
                validation_context,
                stage,
            )
        except GenerationError as error:
            last_error = error
            _retry_rejected_response(stage, error, attempt=attempt)
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


def _normalize_tactical_profile(tactical: dict[str, Any]) -> dict[str, Any]:
    normalized = {**tactical}
    for field in ("fight_role", "economy_plan"):
        if field in normalized:
            normalized[field] = _finish_sentence(normalized[field])
    duration = tactical.get("ending_duration_interpretation")
    if isinstance(duration, dict):
        normalized["ending_duration_interpretation"] = {
            **duration,
            "plan": _finish_sentence(duration.get("plan")),
        }
    return normalized


def _normalize_action_explanations(rows: list[Any]) -> list[Any]:
    return [
        {**row, "instruction": _finish_sentence(row.get("instruction"))}
        if isinstance(row, dict)
        else row
        for row in rows
    ]


def _normalize_category_summaries(rows: list[Any]) -> list[Any]:
    return [
        {**row, "summary": _finish_sentence(row.get("summary"))}
        if isinstance(row, dict)
        else row
        for row in rows
    ]


def normalize_narrative_response(response: dict[str, Any]) -> dict[str, Any]:
    """Normalize presentation-only sentence endings before strict validation.

    Returns:
        A response copy with complete player-facing sentences.

    """
    normalized = {**response}
    if "build_summary" in normalized:
        normalized["build_summary"] = _finish_sentence(normalized["build_summary"])
    tactical = response.get("tactical_profile")
    if isinstance(tactical, dict):
        normalized["tactical_profile"] = _normalize_tactical_profile(tactical)
    actions = response.get("action_explanations")
    if isinstance(actions, list):
        normalized["action_explanations"] = _normalize_action_explanations(actions)
    categories = response.get("category_summaries")
    if isinstance(categories, list):
        normalized["category_summaries"] = _normalize_category_summaries(categories)
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
    parser.add_argument(
        "--concurrency",
        type=positive_int,
        default=DEFAULT_GENERATION_CONCURRENCY,
        metavar="N",
        help=(
            "maximum concurrent hero pipelines "
            f"(default: {DEFAULT_GENERATION_CONCURRENCY})"
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
    return [ability for ability in nested or [] if isinstance(ability, dict)]


def _ability_identity(ability: dict[str, Any]) -> tuple[int | None, str]:
    raw_id = ability.get("id", ability.get("ability_id"))
    raw_name = ability.get("name", ability.get("ability"))
    return (int(raw_id) if isinstance(raw_id, int) else None, str(raw_name or ""))


def _validate_strategy_identity(hero: dict[str, Any], name: str) -> None:
    identity_fields = (
        "snapshot_id",
        "policy_id",
        "context_sha256",
        "kit_basis_sha256",
        "narrative_basis_sha256",
    )
    if (
        not isinstance(hero.get("hero_id"), int)
        or not isinstance(hero.get("path_id"), str)
        or not hero["path_id"].strip()
        or any(not _is_sha256(hero.get(field)) for field in identity_fields)
    ):
        raise GenerationError(f"strategy context omitted exact identity for {name}")


def _validate_hero_abilities(hero: dict[str, Any], name: str) -> None:
    abilities = _abilities(hero)
    if len(abilities) != 4 or any(
        _ability_identity(ability)[0] is None for ability in abilities
    ):
        raise GenerationError(
            f"strategy context omitted four current abilities for {name}"
        )


def _validate_ability_policy_context(hero: dict[str, Any], name: str) -> None:
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


def _validate_policy_projection_context(hero: dict[str, Any], name: str) -> None:
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


def validate_hero_context(hero: dict[str, Any]) -> None:
    """Reject packets that cannot support a closed-policy explanation.

    Raises:
        GenerationError: If identity, mechanics, policy, or projection is incomplete.

    """
    name = str(hero.get("hero") or hero.get("hero_id") or "unknown")
    _validate_strategy_identity(hero, name)
    _validate_hero_abilities(hero, name)
    _validate_ability_policy_context(hero, name)
    ending = hero.get("ending_duration_profile")
    if (
        not isinstance(ending, dict)
        or ending.get("estimand") != "ending_duration_profile"
    ):
        raise GenerationError(
            f"strategy context omitted the ending-duration estimand for {name}"
        )
    _validate_policy_projection_context(hero, name)


def kit_context(hero: dict[str, Any]) -> dict[str, Any]:
    """Return only mechanics and legal ability evidence for the kit stage.

    Returns:
        The ability-only packet supplied to the first model stage.

    """
    return {
        "hero_id": hero.get("hero_id"),
        "path_id": hero.get("path_id"),
        "hero": hero.get("hero"),
        "kit_basis_sha256": hero.get("kit_basis_sha256"),
        "hero_mechanics": hero.get("hero_mechanics"),
        "ability_policy": hero.get("ability_policy"),
    }


def synthesis_context(
    hero: dict[str, Any],
    kit_profile: dict[str, Any],
    item_mechanics: dict[str, dict[str, Any]],
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
    selected_mechanics = [
        {
            **item,
            "mechanics": item_mechanics.get(str(item["item_id"]), {}),
        }
        for item in selected_mechanics
    ]
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
    hero_mechanics = hero.get("hero_mechanics")
    hero_description = (
        hero_mechanics.get("description") if isinstance(hero_mechanics, dict) else None
    )
    return {
        key: hero.get(key)
        for key in (
            "hero_id",
            "path_id",
            "hero",
            "snapshot_id",
            "policy_id",
            "context_sha256",
            "narrative_basis_sha256",
            "ability_policy",
            "ending_duration_profile",
            "core",
            "explainable_actions",
            "projection",
            "interpretation_constraints",
        )
    } | {
        "hero_description": hero_description,
        "policy_summary": policy_summary,
        "selected_action_mechanics": selected_mechanics,
        "preliminary_kit_analysis": kit_profile,
    }


_KIT_TEXT_FIELDS = (
    "primary_role",
    "combat_pattern",
    "economy_tendencies",
    "scaling_profile",
)


def _validate_kit_identity_and_profile(
    response: dict[str, Any],
    hero: dict[str, Any],
    name: str,
) -> None:
    if response.get("hero_id") != hero.get("hero_id"):
        raise GenerationError(f"kit analysis changed hero_id for {name}")
    if response.get("path_id") != hero.get("path_id"):
        raise GenerationError(f"kit analysis changed path_id for {name}")
    if response.get("kit_basis_sha256") != hero.get("kit_basis_sha256"):
        raise GenerationError(f"kit analysis changed kit_basis_sha256 for {name}")
    if any(
        not isinstance(response.get(field), str) or not response[field].strip()
        for field in _KIT_TEXT_FIELDS
    ):
        raise GenerationError(f"kit analysis omitted its tactical profile for {name}")


def _supplied_ability_identities(hero: dict[str, Any]) -> dict[int, str]:
    return {
        ability_id: ability_name
        for ability in _abilities(hero)
        for ability_id, ability_name in (_ability_identity(ability),)
        if ability_id is not None
    }


def _validated_ability_roles(
    roles: object,
    supplied: dict[int, str],
    name: str,
) -> list[dict[str, Any]]:
    if not isinstance(roles, list) or len(roles) != len(supplied):
        raise GenerationError(f"kit analysis omitted ability roles for {name}")
    normalized_roles: list[dict[str, Any]] = []
    seen: set[int] = set()
    for role in roles:
        if not isinstance(role, dict) or not isinstance(role.get("ability_id"), int):
            raise GenerationError(
                f"kit analysis returned an invalid ability for {name}"
            )
        role_data = cast("_KitAbilityRole", role)
        ability_id = int(role_data["ability_id"])
        if ability_id in seen or supplied.get(ability_id) != role_data.get("ability"):
            raise GenerationError(f"kit analysis changed an ability for {name}")
        if any(
            not isinstance(role_data.get(field), str) or not role_data[field].strip()
            for field in ("tactical_role", "scaling_hooks")
        ):
            raise GenerationError(f"kit analysis omitted ability evidence for {name}")
        seen.add(ability_id)
        normalized_roles.append({
            "ability_id": ability_id,
            "ability": str(role_data["ability"]),
            "tactical_role": str(role_data["tactical_role"]).strip(),
            "scaling_hooks": str(role_data["scaling_hooks"]).strip(),
        })
    if seen != set(supplied):
        raise GenerationError(f"kit analysis omitted a supplied ability for {name}")
    return normalized_roles


def _validated_kit_synergies(value: object, name: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(entry, str) or not entry.strip() for entry in value)
    ):
        raise GenerationError(f"kit analysis omitted supplied synergies for {name}")
    return [entry.strip() for entry in cast("list[str]", value)]


def _validated_kit_uncertainties(value: object, name: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(entry, str) or not entry.strip() for entry in value
    ):
        raise GenerationError(f"kit analysis omitted supplied evidence for {name}")
    return [entry.strip() for entry in cast("list[str]", value)]


def validate_kit_response(
    response: dict[str, Any],
    hero: dict[str, Any],
) -> dict[str, Any]:
    """Validate an ability-only profile without admitting invented identities.

    Returns:
        A normalized, fingerprint-bound kit explanation.

    """
    name = str(hero.get("hero") or hero.get("hero_id") or "unknown")
    _validate_kit_identity_and_profile(response, hero, name)
    supplied = _supplied_ability_identities(hero)
    normalized_roles = _validated_ability_roles(
        response.get("ability_roles"), supplied, name
    )
    synergies = _validated_kit_synergies(response.get("synergies"), name)
    uncertainties = _validated_kit_uncertainties(response.get("uncertainties"), name)
    return {
        "hero_id": int(response["hero_id"]),
        "path_id": str(response["path_id"]),
        "hero": name,
        "kit_basis_sha256": str(response["kit_basis_sha256"]),
        "prompt_version": KIT_PROMPT_VERSION,
        **{field: str(response[field]).strip() for field in _KIT_TEXT_FIELDS},
        "ability_roles": normalized_roles,
        "synergies": synergies,
        "uncertainties": uncertainties,
    }


def _build_key(entry: dict[str, Any]) -> BuildKey | None:
    hero_id = entry.get("hero_id")
    path_id = entry.get("path_id")
    if not isinstance(hero_id, int) or not isinstance(path_id, str) or not path_id:
        return None
    return hero_id, path_id


def _existing_entries(path: Path) -> dict[BuildKey, dict[str, Any]]:
    if not path.is_file():
        return {}
    heroes = _load_object(path).get("heroes")
    if not isinstance(heroes, list):
        return {}
    entries: dict[BuildKey, dict[str, Any]] = {}
    for entry in heroes:
        if not isinstance(entry, dict):
            continue
        key = _build_key(entry)
        if key is not None:
            entries[key] = entry
    return entries


def validated_reusable_kit_profiles(
    existing: dict[BuildKey, dict[str, Any]],
    source_heroes: dict[BuildKey, dict[str, Any]],
) -> dict[BuildKey, dict[str, Any]]:
    reusable: dict[BuildKey, dict[str, Any]] = {}
    for build_key, entry in existing.items():
        hero = source_heroes.get(build_key)
        if (
            hero is None
            or entry.get("prompt_version") != KIT_PROMPT_VERSION
            or entry.get("kit_basis_sha256") != hero.get("kit_basis_sha256")
        ):
            continue
        try:
            reusable[build_key] = validate_kit_response(entry, hero)
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
    text = value.strip()
    if CORRUPT_PROSE_PATTERN.search(text):
        raise GenerationError(f"Codex returned corrupted {label} for {hero_name}")
    return text


def _validate_prose_ceiling(text: str, hero_name: str) -> None:
    if ANALYTICS_LEAK_PATTERN.search(text):
        raise GenerationError(f"Codex leaked analytic-unit language for {hero_name}")
    if CAUSAL_PATTERN.search(text):
        raise GenerationError(f"Codex exceeded a non-causal claim for {hero_name}")


def _validate_conditional_instruction(
    instruction: str,
    supplied: dict[str, Any],
    *,
    node_id: str,
) -> None:
    contract = supplied.get("conditional_contract")
    if contract is None:
        return
    if not isinstance(contract, dict):
        raise GenerationError(f"conditional contract is malformed for {node_id}")
    required = (
        "threat",
        "item",
        "comparator_item",
        "mechanic_ref",
        "legal_timing",
        "replacement",
        "execution_mode",
        "failure_condition",
    )
    if any(
        not isinstance(contract.get(field), str) or not str(contract[field]).strip()
        for field in required
    ):
        raise GenerationError(f"conditional contract is incomplete for {node_id}")
    threat_value = contract.get("threat")
    item_id = contract.get("item_id")
    comparator_item_id = contract.get("comparator_item_id")
    identity_checks = (
        threat_value in THREAT_CLASSES,
        _is_positive_int(item_id),
        item_id == supplied.get("action_id"),
        contract.get("item") == supplied.get("action"),
        _is_positive_int(comparator_item_id),
        comparator_item_id != item_id,
        contract.get("evidence_ref") == supplied.get("evidence_ref"),
        contract.get("mechanic_ref") in supplied.get("mechanics_refs", []),
    )
    if not all(identity_checks):
        raise GenerationError(f"conditional contract identity changed for {node_id}")
    normalized = instruction.casefold()
    threat = str(threat_value).replace("_", " ").casefold()
    if threat not in normalized:
        raise GenerationError(f"Codex changed the threat for action {node_id}")
    invented_threats = {
        candidate
        for candidate in THREAT_CLASSES
        if candidate != threat_value and candidate.replace("_", " ") in normalized
    }
    if invented_threats:
        raise GenerationError(f"Codex invented a threat for action {node_id}")
    if not _mentions_item(instruction, str(contract["comparator_item"])):
        raise GenerationError(f"Codex omitted the comparator for action {node_id}")
    enemy_hero_id = contract.get("enemy_hero_id")
    if enemy_hero_id is not None and (
        not isinstance(enemy_hero_id, int)
        or isinstance(enemy_hero_id, bool)
        or enemy_hero_id <= 0
    ):
        raise GenerationError(f"conditional enemy trigger changed for {node_id}")
    if (
        enemy_hero_id is not None
        and re.search(
            rf"\benemy(?:\s+hero)?\s+{int(enemy_hero_id)}\b",
            instruction,
            re.IGNORECASE,
        )
        is None
    ):
        raise GenerationError(f"Codex changed the enemy trigger for action {node_id}")
    checks = (
        (TRIGGER_PATTERN, "trigger"),
        (CHOICE_PATTERN, "replacement"),
        (EXECUTION_PATTERN, "execution"),
        (FAILURE_PATTERN, "failure condition"),
    )
    missing = [
        label for pattern, label in checks if pattern.search(instruction) is None
    ]
    if missing:
        raise GenerationError(
            f"Codex omitted conditional {', '.join(missing)} for action {node_id}"
        )


def _validate_narrative_identity(
    response: dict[str, Any],
    hero: dict[str, Any],
    hero_name: str,
    *,
    require_context_match: bool,
) -> None:
    identity_fields = (
        "hero_id",
        "path_id",
        "snapshot_id",
        "policy_id",
        "narrative_basis_sha256",
    )
    if require_context_match:
        identity_fields = (*identity_fields, "context_sha256")
    for field in identity_fields:
        if response.get(field) != hero.get(field):
            raise GenerationError(f"Codex changed {field} for {hero_name}")


@dataclass(frozen=True)
class _ValidatedNarrativeOverview:
    primary_role: str
    fight_role: str
    economy_plan: str
    ending: dict[str, Any]
    ending_plan: str
    build_summary: str


def _validated_narrative_overview(
    response: dict[str, Any],
    hero: dict[str, Any],
    hero_name: str,
) -> _ValidatedNarrativeOverview:
    tactical = response.get("tactical_profile")
    if not isinstance(tactical, dict):
        raise GenerationError(f"Codex omitted tactical_profile for {hero_name}")
    primary_role = _validate_complete_sentence(
        tactical.get("primary_role"), "primary role", hero_name
    )
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
    return _ValidatedNarrativeOverview(
        primary_role=primary_role,
        fight_role=fight_role,
        economy_plan=economy_plan,
        ending=ending,
        ending_plan=ending_plan,
        build_summary=summary,
    )


def _validated_action_explanation(
    explanation: dict[str, Any],
    supplied: dict[str, Any],
    hero_name: str,
) -> dict[str, str]:
    node_id = str(explanation["node_id"])
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
    _validate_conditional_instruction(
        instruction,
        supplied,
        node_id=node_id,
    )
    _validate_prose_ceiling(instruction, hero_name)
    return {
        "node_id": node_id,
        "evidence_ref": str(explanation["evidence_ref"]),
        "instruction": instruction,
    }


def _validated_action_explanations(
    response: dict[str, Any],
    hero: dict[str, Any],
    hero_name: str,
) -> tuple[list[dict[str, str]], list[Any]]:

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
    normalized_actions: list[dict[str, str]] = []
    for explanation in explanations:
        if not isinstance(explanation, dict):
            raise GenerationError(f"Codex returned a malformed action for {hero_name}")
        node_id = str(explanation["node_id"])
        normalized_actions.append(
            _validated_action_explanation(
                explanation,
                supplied_by_node[node_id],
                hero_name,
            )
        )
    return normalized_actions, supplied_actions


def _validated_category_summary(
    source_category: dict[str, Any],
    category: dict[str, Any],
    supplied_actions: list[Any],
    all_items: set[str],
    hero_name: str,
) -> dict[str, str]:
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
    if not mentioned or not mentioned <= (category_items | allowed_replacement_refs):
        raise GenerationError(
            f"Codex used missing or cross-category items in {source_category.get('name')}"
        )
    _validate_optional_category_semantics(source_category, text)
    _validate_prose_ceiling(text, hero_name)
    return {
        "category": str(category.get("category")),
        "summary": text,
    }


def _validate_optional_category_semantics(
    source_category: dict[str, Any],
    text: str,
) -> None:
    if not source_category.get("optional"):
        return
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
        raise GenerationError(f"Codex removed the optional trigger for {category_name}")


def _validated_category_summaries(
    response: dict[str, Any],
    hero: dict[str, Any],
    supplied_actions: list[Any],
    hero_name: str,
) -> list[dict[str, str]]:

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
    normalized_categories: list[dict[str, str]] = []
    for source_category, category in zip(categories, summaries, strict=True):
        if not isinstance(source_category, dict) or not isinstance(category, dict):
            raise GenerationError(
                f"Codex returned a malformed category for {hero_name}"
            )
        normalized_categories.append(
            _validated_category_summary(
                cast("_ProjectionCategory", source_category),
                cast("_ProjectionCategory", category),
                supplied_actions,
                all_items,
                hero_name,
            )
        )
    return normalized_categories


def validate_response(
    response: dict[str, Any],
    hero: dict[str, Any],
    *,
    require_context_match: bool = True,
) -> dict[str, Any]:
    """Admit prose only when it is an exact explanation of the closed policy.

    Returns:
        A normalized explanation whose identifiers and action set are unchanged.

    """
    hero_name = str(hero.get("hero") or hero.get("hero_id") or "unknown")
    _validate_narrative_identity(
        response,
        hero,
        hero_name,
        require_context_match=require_context_match,
    )
    overview = _validated_narrative_overview(response, hero, hero_name)
    normalized_actions, supplied_actions = _validated_action_explanations(
        response,
        hero,
        hero_name,
    )
    normalized_categories = _validated_category_summaries(
        response,
        hero,
        supplied_actions,
        hero_name,
    )
    combined = " ".join(
        [
            overview.build_summary,
            overview.fight_role,
            overview.economy_plan,
            overview.ending_plan,
        ]
        + [row["instruction"] for row in normalized_actions]
        + [row["summary"] for row in normalized_categories]
    )
    _validate_prose_ceiling(combined, hero_name)
    return {
        "hero_id": int(response["hero_id"]),
        "path_id": str(response["path_id"]),
        "hero": hero_name,
        "snapshot_id": str(response["snapshot_id"]),
        "policy_id": str(response["policy_id"]),
        "context_sha256": str(hero.get("context_sha256")),
        "narrative_basis_sha256": str(response["narrative_basis_sha256"]),
        "prompt_version": PROMPT_VERSION,
        "tactical_profile": {
            "primary_role": overview.primary_role.strip(),
            "fight_role": overview.fight_role,
            "economy_plan": overview.economy_plan,
            "ending_duration_interpretation": {
                "estimand": str(overview.ending["estimand"]),
                "strongest_phase": str(overview.ending["strongest_phase"]),
                "weakest_phase": str(overview.ending["weakest_phase"]),
                "plan": overview.ending_plan,
            },
        },
        "build_summary": overview.build_summary,
        "action_explanations": normalized_actions,
        "category_summaries": normalized_categories,
    }


def _write_artifact(path: Path, document: dict[str, Any]) -> None:
    atomic_write_json(path, document)


def _artifact_document(
    source: dict[str, Any],
    generated: dict[BuildKey, dict[str, Any]],
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
            generated[key] for key in sorted(generated) if key[0] in requested_hero_ids
        ],
    }


def _kit_artifact_document(
    source: dict[str, Any],
    generated: dict[BuildKey, dict[str, Any]],
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
    existing: dict[BuildKey, dict[str, Any]],
    source_heroes: dict[BuildKey, dict[str, Any]],
) -> dict[BuildKey, dict[str, Any]]:
    """Return only exact-policy, exact-snapshot narrative artifacts.

    Returns:
        Revalidated entries keyed by hero ID.

    """
    reusable: dict[BuildKey, dict[str, Any]] = {}
    identity_fields = (
        "snapshot_id",
        "policy_id",
        "context_sha256",
        "narrative_basis_sha256",
    )
    for build_key, entry in existing.items():
        hero = source_heroes.get(build_key)
        if (
            hero is None
            or entry.get("prompt_version") not in REUSABLE_PROMPT_VERSIONS
            or any(entry.get(field) != hero.get(field) for field in identity_fields)
        ):
            continue
        try:
            reusable[build_key] = validate_response(entry, hero)
        except GenerationError:
            continue
    return reusable


@dataclass
class _NarrativeGenerationRun:
    args: argparse.Namespace
    source: dict[str, Any]
    selected_heroes: list[dict[str, Any]]
    requested_hero_ids: set[int]
    kit_schema: Path
    kit_output: Path
    generated_narratives: dict[BuildKey, dict[str, Any]]
    kit_profiles: dict[BuildKey, dict[str, Any]]
    artifact_lock: threading.Lock
    request_limiter: _RequestLimiter


def _prepare_narrative_generation(
    args: argparse.Namespace,
) -> _NarrativeGenerationRun:
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
    requested_hero_ids = {int(hero["hero_id"]) for hero in selected}
    if args.hero is None:
        requested_hero_ids.update(
            int(exclusion["hero_id"])
            for exclusion in source.get("exclusions") or []
            if isinstance(exclusion, dict) and isinstance(exclusion.get("hero_id"), int)
        )
    source_heroes = {
        (int(hero["hero_id"]), str(hero["path_id"])): hero for hero in selected
    }
    return _NarrativeGenerationRun(
        args=args,
        source=source,
        selected_heroes=selected,
        requested_hero_ids=requested_hero_ids,
        kit_schema=kit_schema,
        kit_output=kit_output,
        generated_narratives=validated_reusable_entries(
            _existing_entries(args.output),
            source_heroes,
        ),
        kit_profiles=validated_reusable_kit_profiles(
            _existing_entries(kit_output),
            source_heroes,
        ),
        artifact_lock=threading.Lock(),
        request_limiter=_RequestLimiter(args.concurrency),
    )


def _write_kit_profile_artifact(run: _NarrativeGenerationRun) -> None:
    _write_artifact(
        run.kit_output,
        _kit_artifact_document(
            run.source,
            run.kit_profiles,
            model=run.args.kit_model,
        ),
    )


def _write_narrative_artifact(run: _NarrativeGenerationRun) -> None:
    _write_artifact(
        run.args.output,
        _artifact_document(
            run.source,
            run.generated_narratives,
            requested_hero_ids=run.requested_hero_ids,
            kit_model=run.args.kit_model,
            synthesis_model=run.args.model,
        ),
    )


def _checkpoint_kit_profile(
    run: _NarrativeGenerationRun,
    build_key: BuildKey,
    kit_profile: dict[str, Any],
) -> None:
    with run.artifact_lock:
        run.kit_profiles[build_key] = kit_profile
        _write_kit_profile_artifact(run)


def _checkpoint_generated_narrative(
    run: _NarrativeGenerationRun,
    build_key: BuildKey,
    narrative: dict[str, Any],
) -> None:
    with run.artifact_lock:
        run.generated_narratives[build_key] = narrative
        _write_narrative_artifact(run)


def _write_completed_generation_artifacts(run: _NarrativeGenerationRun) -> None:
    with run.artifact_lock:
        _write_kit_profile_artifact(run)
        _write_narrative_artifact(run)


def _kit_profile_for_narrative(
    run: _NarrativeGenerationRun,
    hero: dict[str, Any],
    *,
    index: int,
) -> dict[str, Any]:
    build_key = int(hero["hero_id"]), str(hero["path_id"])
    kit_profile = run.kit_profiles.get(build_key)
    if not run.args.force and kit_profile is not None:
        return kit_profile
    print(
        f"[{index}/{len(run.selected_heroes)}] Kit ({run.args.kit_model}): "
        f"{hero.get('hero')} / {hero.get('path_label') or hero.get('path_id')}",
        file=sys.stderr,
    )
    kit_profile = generate_validated_response(
        kit_context(hero),
        hero,
        GenerationStage(
            schema_path=run.kit_schema,
            model=run.args.kit_model,
            prompt=KIT_PROMPT,
            identity_fields=("hero_id", "path_id", "kit_basis_sha256"),
            validator=validate_kit_response,
            label=f"kit analysis for {hero.get('hero')}",
            max_attempts=run.args.max_attempts,
        ),
        request_limiter=run.request_limiter,
    )
    _checkpoint_kit_profile(run, build_key, kit_profile)
    return kit_profile


def _generate_hero_narrative(
    run: _NarrativeGenerationRun,
    hero: dict[str, Any],
    *,
    index: int,
) -> None:
    build_key = int(hero["hero_id"]), str(hero["path_id"])
    if not run.args.force and build_key in run.generated_narratives:
        print(
            f"[{index}/{len(run.selected_heroes)}] reuse {hero.get('hero')} / "
            f"{hero.get('path_label') or hero.get('path_id')}",
            file=sys.stderr,
        )
        return
    kit_profile = _kit_profile_for_narrative(run, hero, index=index)
    print(
        f"[{index}/{len(run.selected_heroes)}] Synthesis ({run.args.model}): "
        f"{hero.get('hero')} / {hero.get('path_label') or hero.get('path_id')}",
        file=sys.stderr,
    )
    model_context = synthesis_context(
        hero,
        kit_profile,
        run.source["item_mechanics"],
    )
    narrative = generate_validated_response(
        model_context,
        hero,
        GenerationStage(
            schema_path=run.args.schema,
            model=run.args.model,
            prompt=PROMPT,
            identity_fields=(
                "hero_id",
                "path_id",
                "snapshot_id",
                "policy_id",
                "context_sha256",
                "narrative_basis_sha256",
            ),
            validator=validate_response,
            label=f"narrative synthesis for {hero.get('hero')}",
            max_attempts=run.args.max_attempts,
            normalizer=normalize_narrative_response,
        ),
        request_limiter=run.request_limiter,
    )
    _checkpoint_generated_narrative(run, build_key, narrative)


def _pending_hero_pipelines(
    run: _NarrativeGenerationRun,
) -> list[tuple[int, dict[str, Any]]]:
    pending: list[tuple[int, dict[str, Any]]] = []
    selected_count = len(run.selected_heroes)
    for index, hero in enumerate(run.selected_heroes, start=1):
        build_key = int(hero["hero_id"]), str(hero["path_id"])
        if not run.args.force and build_key in run.generated_narratives:
            print(
                f"[{index}/{selected_count}] reuse {hero.get('hero')}",
                file=sys.stderr,
            )
        else:
            pending.append((index, hero))
    return pending


def _generate_pending_hero_pipelines(
    run: _NarrativeGenerationRun,
    pending: list[tuple[int, dict[str, Any]]],
) -> dict[BuildKey, GenerationError]:
    failures: dict[BuildKey, GenerationError] = {}
    worker_count = min(run.args.concurrency, len(pending))
    print(
        f"Generating {len(pending)} hero pipeline(s) with up to "
        f"{worker_count} concurrent worker(s).",
        file=sys.stderr,
    )
    with ThreadPoolExecutor(
        max_workers=worker_count,
        thread_name_prefix="deadlock-narrative",
    ) as executor:
        futures = {
            executor.submit(_generate_hero_narrative, run, hero, index=index): (
                int(hero["hero_id"]),
                str(hero["path_id"]),
            )
            for index, hero in pending
        }
        for future in as_completed(futures):
            build_key = futures[future]
            try:
                future.result()
            except GenerationError as error:
                failures[build_key] = error
    return failures


def _raise_hero_pipeline_failures(
    run: _NarrativeGenerationRun,
    failures: dict[BuildKey, GenerationError],
) -> None:
    if not failures:
        return
    failure_details = "; ".join(
        f"{hero.get('hero')}/{hero.get('path_id')}: {failures[build_key]}"
        for hero in run.selected_heroes
        if (build_key := (int(hero["hero_id"]), str(hero["path_id"]))) in failures
    )
    raise GenerationError(f"hero generation failed: {failure_details}")


def _generate_selected_narratives(run: _NarrativeGenerationRun) -> None:
    pending = _pending_hero_pipelines(run)
    if pending:
        failures = _generate_pending_hero_pipelines(run, pending)
        _raise_hero_pipeline_failures(run, failures)
    _write_completed_generation_artifacts(run)


def main(argv: list[str] | None = None) -> int:
    args = parse_args() if argv is None else parse_args(argv)
    try:
        run = _prepare_narrative_generation(args)
        _generate_selected_narratives(run)
        print(f"Wrote {len(run.generated_narratives)} narrative(s): {args.output}")
        return 0
    except GenerationError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
