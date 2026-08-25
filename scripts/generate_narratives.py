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
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

from deadlock_build_sync.artifacts import atomic_write_json
from deadlock_build_sync.narratives import (
    DEFAULT_SYNTHESIS_MODEL,
    NARRATIVE_PROMPT_VERSION,
    NARRATIVE_SCHEMA_VERSION,
)
from deadlock_build_sync.strategy_context import (
    StrategyContextError,
    validate_strategy_context_document,
)

type BuildKey = tuple[int, str]

SCHEMA_VERSION = NARRATIVE_SCHEMA_VERSION
PROMPT_VERSION = NARRATIVE_PROMPT_VERSION
REUSABLE_PROMPT_VERSIONS = frozenset({PROMPT_VERSION})
DEFAULT_GENERATION_ATTEMPTS = 3
DEFAULT_GENERATION_CONCURRENCY = 8
DEFAULT_RATE_LIMIT_BACKOFF_SECONDS = 1.0
MAX_RATE_LIMIT_BACKOFF_SECONDS = 60.0
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

PROMPT = """
Write one compact in-game Deadlock build description for a closed policy packet.
Return only the schema-constrained JSON object.

Authority and scope:
- The deterministic policy, ability order, item order, Queue projection, item
  annotations, and category text are already final. Do not rewrite them.
- Copy hero_id, path_id, snapshot_id, policy_id, context_sha256, and
  narrative_basis_sha256 exactly.
- Use only supplied hero mechanics, ability policy, CORE item names, and policy
  summary. Never invent a
  mechanic, numeric effect, combo, matchup, timing, target, or causal benefit.
- A descriptive association may be called observed or associated only. Never
  claim an item causes wins or improves win probability.
- Never use cause, causes, caused, guarantee, or guarantees anywhere in the
  prose, including when paraphrasing a supplied mechanic. Use neutral mechanic
  verbs such as triggers, applies, deals, grants, or reduces instead.
- Price tiers are price tiers. They are not early/mid/late phases and are never
  paired with equal quarters of the ability order.

build_description:
- In 80–700 plain-text characters, describe how the hero plays, what the supported
  CORE path emphasizes, and how to approach fights.
- Keep it useful and hero-specific. Do not dump stats, repeat UI labels, give item
  hover instructions, or describe every tier menu.
- Finish with a complete sentence. No Markdown lists.
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


def normalize_narrative_response(response: dict[str, Any]) -> dict[str, Any]:
    """Normalize the build-description sentence ending before validation.

    Returns:
        A response copy with a complete build description.

    """
    normalized = {**response}
    if "build_description" in normalized:
        normalized["build_description"] = _finish_sentence(
            normalized["build_description"]
        )
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
        "--hero",
        action="append",
        help="limit generation to a hero name or numeric ID; repeatable",
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
        help=f"generation attempts per build (default: {DEFAULT_GENERATION_ATTEMPTS})",
    )
    parser.add_argument(
        "--concurrency",
        type=positive_int,
        default=DEFAULT_GENERATION_CONCURRENCY,
        metavar="N",
        help=(
            "maximum concurrent build descriptions "
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


def synthesis_context(
    hero: dict[str, Any],
) -> dict[str, Any]:
    """Return the smallest closed packet needed for one build description.

    Returns:
        Identity, hero mechanics, ability policy, and final CORE names.

    """
    core = hero.get("core")
    core_items = core.get("items") if isinstance(core, dict) else None
    selected_core = [
        {
            "item_id": item.get("item_id"),
            "item": item.get("item"),
            "tier": item.get("tier"),
        }
        for item in core_items or []
        if isinstance(item, dict)
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
            "path_label",
            "hero_mechanics",
            "ability_policy",
        )
    } | {
        "core_items": selected_core,
        "policy_summary": policy_summary,
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


def validate_response(
    response: dict[str, Any],
    hero: dict[str, Any],
    *,
    require_context_match: bool = True,
) -> dict[str, Any]:
    """Admit one grounded description with an exact artifact identity.

    Returns:
        A normalized build description whose identifiers are unchanged.

    Raises:
        GenerationError: If the response is incomplete, stale, or unsafe.

    """
    hero_name = str(hero.get("hero") or hero.get("hero_id") or "unknown")
    _validate_narrative_identity(
        response,
        hero,
        hero_name,
        require_context_match=require_context_match,
    )
    description = _validate_complete_sentence(
        response.get("build_description"), "build description", hero_name
    )
    if not 80 <= len(description) <= 700:
        raise GenerationError(
            f"Codex returned an out-of-range build description for {hero_name}"
        )
    _validate_prose_ceiling(description, hero_name)
    return {
        "hero_id": int(response["hero_id"]),
        "path_id": str(response["path_id"]),
        "hero": hero_name,
        "snapshot_id": str(response["snapshot_id"]),
        "policy_id": str(response["policy_id"]),
        "context_sha256": str(hero.get("context_sha256")),
        "narrative_basis_sha256": str(response["narrative_basis_sha256"]),
        "prompt_version": PROMPT_VERSION,
        "build_description": description,
    }


def _write_artifact(path: Path, document: dict[str, Any]) -> None:
    atomic_write_json(path, document)


def _artifact_document(
    source: dict[str, Any],
    generated: dict[BuildKey, dict[str, Any]],
    *,
    requested_hero_ids: set[int],
    model: str | None,
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
        "generator": "codex exec (build description only)",
        "prompt_version": PROMPT_VERSION,
        "model": model,
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
    generated_narratives: dict[BuildKey, dict[str, Any]]
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
        generated_narratives=validated_reusable_entries(
            _existing_entries(args.output),
            source_heroes,
        ),
        artifact_lock=threading.Lock(),
        request_limiter=_RequestLimiter(args.concurrency),
    )


def _write_narrative_artifact(run: _NarrativeGenerationRun) -> None:
    _write_artifact(
        run.args.output,
        _artifact_document(
            run.source,
            run.generated_narratives,
            requested_hero_ids=run.requested_hero_ids,
            model=run.args.model,
        ),
    )


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
        _write_narrative_artifact(run)


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
    print(
        f"[{index}/{len(run.selected_heroes)}] Description ({run.args.model}): "
        f"{hero.get('hero')} / {hero.get('path_label') or hero.get('path_id')}",
        file=sys.stderr,
    )
    model_context = synthesis_context(hero)
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
            label=f"build description for {hero.get('hero')}",
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
