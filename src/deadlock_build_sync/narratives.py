from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from .purchase_guide import standard_category_description

if TYPE_CHECKING:
    from pathlib import Path

    from .api import Patch
    from .purchase_guide import PurchaseGuide

NARRATIVE_SCHEMA_VERSION = 4
NARRATIVE_PROMPT_VERSION = 19
DEFAULT_KIT_MODEL = "gpt-5.6-luna"
DEFAULT_SYNTHESIS_MODEL = "gpt-5.6-sol"


class NarrativeError(RuntimeError):
    """Raised when an AI-authored explanation artifact is invalid or stale."""


@dataclass(frozen=True)
class NarrativeCatalog:
    snapshot_id: str
    patch_identity: str
    client_version: int
    match_mode: str
    game_mode: str
    source_context_sha256: str
    requested_hero_ids: frozenset[int]
    exclusions: dict[int, str]
    heroes: dict[int, dict[str, Any]]


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _require_sha(path: Path, value: Any, label: str) -> str:
    if not _is_sha256(value):
        raise NarrativeError(f"{path} has no valid {label} fingerprint")
    return str(value)


def _require_identity(path: Path, entry: dict[str, Any], snapshot_id: str) -> None:
    if entry.get("snapshot_id") != snapshot_id:
        raise NarrativeError(f"{path} contains a hero from another snapshot")
    for field, label in (
        ("policy_id", "policy"),
        ("context_sha256", "context"),
        ("narrative_basis_sha256", "narrative basis"),
    ):
        _require_sha(path, entry.get(field), label)


def load_narrative_catalog(path: Path) -> NarrativeCatalog:
    """Load a complete narrative artifact and validate its compatibility envelope.

    Returns:
        An exact-snapshot catalog ready for deterministic admission.

    Raises:
        NarrativeError: If schema, identity, coverage, or hero data is incomplete.

    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise NarrativeError(
            f"could not read narrative artifact {path}: {error}"
        ) from error
    if (
        not isinstance(data, dict)
        or data.get("schema_version") != NARRATIVE_SCHEMA_VERSION
    ):
        raise NarrativeError(
            f"{path} is not a supported narrative artifact; regenerate it"
        )
    if data.get("prompt_version") != NARRATIVE_PROMPT_VERSION:
        raise NarrativeError(f"{path} was generated with an outdated tactical prompt")
    snapshot_id = _require_sha(path, data.get("snapshot_id"), "snapshot")
    source_context = _require_sha(
        path,
        data.get("source_context_sha256"),
        "source context",
    )
    patch = data.get("patch")
    cohort = data.get("cohort")
    requested = data.get("requested_hero_ids")
    exclusions = data.get("exclusions")
    entries = data.get("heroes")
    header_checks = (
        isinstance(patch, dict) and _is_sha256(patch.get("identity")),
        isinstance(cohort, dict),
        isinstance(cohort, dict) and isinstance(cohort.get("client_version"), int),
        isinstance(cohort, dict) and isinstance(cohort.get("match_mode"), str),
        isinstance(cohort, dict) and isinstance(cohort.get("game_mode"), str),
        isinstance(requested, list)
        and all(isinstance(hero_id, int) for hero_id in requested),
        isinstance(exclusions, list),
        isinstance(entries, list),
    )
    if not all(header_checks):
        raise NarrativeError(
            f"{path} is missing its snapshot, cohort, or coverage data"
        )
    exclusion_map: dict[int, str] = {}
    for exclusion in exclusions:
        if (
            not isinstance(exclusion, dict)
            or not isinstance(exclusion.get("hero_id"), int)
            or not isinstance(exclusion.get("reason"), str)
            or not exclusion["reason"].strip()
        ):
            raise NarrativeError(f"{path} contains an invalid hero exclusion")
        exclusion_map[int(exclusion["hero_id"])] = str(exclusion["reason"]).strip()
    heroes: dict[int, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("hero_id"), int):
            raise NarrativeError(f"{path} contains an invalid hero narrative")
        if entry.get("prompt_version") != NARRATIVE_PROMPT_VERSION:
            raise NarrativeError(
                f"{path} contains a hero generated with an outdated tactical prompt"
            )
        _require_identity(path, entry, snapshot_id)
        hero_id = int(entry["hero_id"])
        if hero_id in heroes:
            raise NarrativeError(f"{path} contains duplicate hero {hero_id}")
        heroes[hero_id] = entry
    requested_ids = set(requested)
    if set(heroes) & set(exclusion_map):
        raise NarrativeError(f"{path} both includes and excludes a hero")
    if set(heroes) | set(exclusion_map) != requested_ids:
        raise NarrativeError(f"{path} does not cover every requested hero")
    return NarrativeCatalog(
        snapshot_id=snapshot_id,
        patch_identity=str(patch["identity"]),
        client_version=int(cohort["client_version"]),
        match_mode=str(cohort["match_mode"]),
        game_mode=str(cohort["game_mode"]),
        source_context_sha256=source_context,
        requested_hero_ids=frozenset(requested_ids),
        exclusions=exclusion_map,
        heroes=heroes,
    )


def apply_narrative(
    guide: PurchaseGuide,
    context: dict[str, Any],
    patch: Patch,
    catalog: NarrativeCatalog,
) -> PurchaseGuide:
    """Admit prose only when snapshot, policy, context, and projection are exact.

    Returns:
        A guide with summaries replaced while all executable fields remain unchanged.

    Raises:
        NarrativeError: If the artifact is stale, incomplete, or changes category identity.

    """
    if catalog.patch_identity != patch.identity:
        raise NarrativeError("narrative artifact patch identity does not match the run")
    if catalog.snapshot_id != guide.snapshot_id:
        raise NarrativeError("narrative artifact snapshot does not match the guide")
    if catalog.client_version != guide.client_version:
        raise NarrativeError(
            "narrative artifact client version does not match the guide"
        )
    if catalog.match_mode != guide.match_mode:
        raise NarrativeError("narrative artifact match mode does not match the guide")
    entry = catalog.heroes.get(guide.hero_id)
    if entry is None:
        reason = catalog.exclusions.get(guide.hero_id)
        suffix = f": {reason}" if reason else ""
        raise NarrativeError(f"narrative artifact is missing {guide.hero_name}{suffix}")
    exact_fields = (
        ("snapshot_id", guide.snapshot_id, "snapshot"),
        ("policy_id", guide.policy_id, "policy"),
        ("context_sha256", context.get("context_sha256"), "context"),
        (
            "narrative_basis_sha256",
            context.get("narrative_basis_sha256"),
            "narrative basis",
        ),
    )
    for field, expected, label in exact_fields:
        if entry.get(field) != expected:
            raise NarrativeError(
                f"{label} changed for {guide.hero_name}; regenerate the artifact"
            )
    summary = entry.get("build_summary")
    category_summaries = entry.get("category_summaries")
    if (
        not isinstance(summary, str)
        or not summary.strip()
        or not isinstance(category_summaries, list)
    ):
        raise NarrativeError(f"narrative for {guide.hero_name} is incomplete")
    summaries: dict[str, str] = {}
    for category in category_summaries:
        if (
            not isinstance(category, dict)
            or not isinstance(category.get("category"), str)
            or not isinstance(category.get("summary"), str)
            or not category["summary"].strip()
            or category["category"] in summaries
        ):
            raise NarrativeError(
                f"narrative for {guide.hero_name} has invalid category summaries"
            )
        summaries[str(category["category"])] = str(category["summary"]).strip()
    category_names = {category.name for category in guide.rendered_categories}
    if set(summaries) != category_names:
        raise NarrativeError(
            f"narrative for {guide.hero_name} changed the projection categories"
        )
    categories = tuple(
        replace(
            category,
            description=(
                standard_category_description(category.name) or summaries[category.name]
            ),
        )
        for category in guide.rendered_categories
    )
    return replace(guide, summary=summary.strip(), categories=categories)
