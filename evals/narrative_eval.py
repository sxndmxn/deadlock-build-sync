from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any

from deepeval.test_case import LLMTestCase

from scripts import generate_narratives

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTEXT_PATH = Path(
    os.environ.get(
        "DEADLOCK_BUILD_SYNC_EVAL_CONTEXT",
        str(PROJECT_ROOT / "generated/strategy-context.json"),
    )
).expanduser()
SCHEMA_PATH = PROJECT_ROOT / "schemas/narrative-response.schema.json"
KIT_SCHEMA_PATH = PROJECT_ROOT / "schemas/kit-analysis-response.schema.json"
EVAL_TIMEOUT_SECONDS = 120.0
RELIABILITY_REPEATS = 3
DEFAULT_CASES = {
    "Kelvin": "baseline complete ability path",
    "Shiv": "tier-completion regression",
    "Abrams": "close-range frontline grounding",
    "Grey Talon": "new-roster artifact coverage",
    "Vyper": "new-roster tactical grounding",
    "Dynamo": "support and rescue grounding",
    "Haze": "scaling carry economy plan",
    "Lash": "mobile initiator sequencing",
    "McGinnis": "objective and area-control grounding",
    "Vindicta": "ranged pick positioning",
}


class NarrativeEvalError(RuntimeError):
    """Raised when narrative evaluation cases cannot be constructed."""


@dataclass(frozen=True)
class NarrativeCase:
    """One representative hero context and its regression purpose."""

    hero: dict[str, Any]
    regression: str

    @property
    def name(self) -> str:
        """The display name for this evaluation case.

        Returns:
            The hero name from the exported context.

        """
        return str(self.hero.get("hero") or self.hero.get("hero_id") or "unknown")


def _load_context(path: Path) -> list[dict[str, Any]]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise NarrativeEvalError(
            f"could not read {path}; run export-context first: {error}"
        ) from error
    heroes = document.get("heroes") if isinstance(document, dict) else None
    if not isinstance(heroes, list) or not all(
        isinstance(hero, dict) for hero in heroes
    ):
        raise NarrativeEvalError(f"{path} does not contain a valid heroes array")
    return heroes


def load_cases(
    context_path: Path = DEFAULT_CONTEXT_PATH,
    hero_names: list[str] | None = None,
) -> list[NarrativeCase]:
    """Load representative cases from an exported production context.

    Returns:
        Cases in the requested hero order.

    Raises:
        NarrativeEvalError: If the context or requested heroes are invalid.

    """
    requested = hero_names if hero_names is not None else list(DEFAULT_CASES)
    if not requested or any(not name.strip() for name in requested):
        raise NarrativeEvalError("evaluation hero names must be non-empty strings")
    heroes_by_name = {
        str(hero.get("hero") or "").casefold(): hero
        for hero in _load_context(context_path)
    }
    missing = [name for name in requested if name.casefold() not in heroes_by_name]
    if missing:
        raise NarrativeEvalError(
            "evaluation context is missing hero(es): " + ", ".join(missing)
        )
    return [
        NarrativeCase(
            hero=heroes_by_name[name.casefold()],
            regression=DEFAULT_CASES.get(name, "configured case"),
        )
        for name in requested
    ]


def generate_test_case(
    case: NarrativeCase,
    *,
    model: str | None = None,
    kit_model: str | None = None,
    timeout_seconds: float = EVAL_TIMEOUT_SECONDS,
) -> LLMTestCase:
    """Run a case through both production generation stages.

    Returns:
        A DeepEval test case containing the structured Codex response.

    """
    response, kit_profile = _generate_staged_response(
        case,
        model=model,
        kit_model=kit_model,
        timeout_seconds=timeout_seconds,
    )
    return LLMTestCase(
        name=case.name,
        input=_staged_prompt(),
        actual_output=json.dumps(response, ensure_ascii=False),
        context=[json.dumps(case.hero, ensure_ascii=False)],
        metadata={
            "hero": case.name,
            "hero_id": case.hero.get("hero_id"),
            "regression": case.regression,
            "kit_model": kit_model or generate_narratives.DEFAULT_KIT_MODEL,
            "synthesis_model": model or generate_narratives.DEFAULT_SYNTHESIS_MODEL,
            "kit_profile": kit_profile,
        },
    )


def _staged_prompt() -> str:
    return (
        "KIT ANALYSIS STAGE\n"
        + generate_narratives.KIT_PROMPT
        + "\n\nSYNTHESIS STAGE\n"
        + generate_narratives.PROMPT
    )


def _generate_staged_response(
    case: NarrativeCase,
    *,
    model: str | None,
    kit_model: str | None,
    timeout_seconds: float,
    max_attempts: int = 1,
) -> tuple[dict[str, Any], dict[str, Any]]:
    resolved_kit_model = kit_model or generate_narratives.DEFAULT_KIT_MODEL
    resolved_synthesis_model = model or generate_narratives.DEFAULT_SYNTHESIS_MODEL
    kit_profile = generate_narratives.generate_validated_response(
        generate_narratives.kit_context(case.hero),
        case.hero,
        generate_narratives.GenerationStage(
            schema_path=KIT_SCHEMA_PATH,
            model=resolved_kit_model,
            prompt=generate_narratives.KIT_PROMPT,
            identity_fields=("hero_id", "kit_basis_sha256"),
            validator=generate_narratives.validate_kit_response,
            label=f"kit analysis for {case.name}",
            max_attempts=max_attempts,
            timeout_seconds=timeout_seconds,
        ),
    )
    synthesis_context = generate_narratives.synthesis_context(case.hero, kit_profile)
    response = generate_narratives.generate_validated_response(
        synthesis_context,
        case.hero,
        generate_narratives.GenerationStage(
            schema_path=SCHEMA_PATH,
            model=resolved_synthesis_model,
            prompt=generate_narratives.PROMPT,
            identity_fields=(
                "hero_id",
                "context_sha256",
                "narrative_basis_sha256",
            ),
            validator=generate_narratives.validate_response,
            label=f"narrative synthesis for {case.name}",
            max_attempts=max_attempts,
            timeout_seconds=timeout_seconds,
            normalizer=generate_narratives.normalize_narrative_response,
        ),
    )
    return response, kit_profile


def generate_reliability_test_case(
    case: NarrativeCase,
    *,
    repeats: int = RELIABILITY_REPEATS,
    model: str | None = None,
    kit_model: str | None = None,
    timeout_seconds: float = EVAL_TIMEOUT_SECONDS,
) -> LLMTestCase:
    """Generate repeated responses while retaining timeouts as scored samples.

    Returns:
        A DeepEval test case containing every response, latency, or error.

    Raises:
        NarrativeEvalError: If fewer than two repeats are requested.

    """
    if repeats < 2:
        raise NarrativeEvalError("reliability evaluation requires at least 2 repeats")
    samples: list[dict[str, Any]] = []
    for attempt in range(1, repeats + 1):
        started = monotonic()
        try:
            response, kit_profile = _generate_staged_response(
                case,
                model=model,
                kit_model=kit_model,
                timeout_seconds=timeout_seconds,
                max_attempts=generate_narratives.DEFAULT_GENERATION_ATTEMPTS,
            )
        except generate_narratives.GenerationError as error:
            samples.append({
                "attempt": attempt,
                "duration_seconds": round(monotonic() - started, 3),
                "error": str(error),
            })
        else:
            samples.append({
                "attempt": attempt,
                "duration_seconds": round(monotonic() - started, 3),
                "output": response,
                "kit_profile": kit_profile,
            })
    return LLMTestCase(
        name=f"{case.name} reliability",
        input=_staged_prompt(),
        actual_output=json.dumps(samples, ensure_ascii=False),
        context=[json.dumps(case.hero, ensure_ascii=False)],
        metadata={
            "hero": case.name,
            "hero_id": case.hero.get("hero_id"),
            "regression": case.regression,
            "repeats": repeats,
            "timeout_seconds": timeout_seconds,
            "kit_model": kit_model or generate_narratives.DEFAULT_KIT_MODEL,
            "synthesis_model": model or generate_narratives.DEFAULT_SYNTHESIS_MODEL,
        },
    )
