from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from pathlib import Path

    from .api import Patch
    from .purchase_guide import PurchaseGuide

NARRATIVE_SCHEMA_VERSION = 9
NARRATIVE_GENERATOR_VERSION = 1
MINIMUM_BUILD_DESCRIPTION_CHARACTERS = 80
MAXIMUM_BUILD_DESCRIPTION_CHARACTERS = 700
NARRATIVE_FIELD_SURFACES = {
    "build_description": ("player.description",),
}


class NarrativeError(RuntimeError):
    """Raised when a deterministic description artifact is invalid or stale."""


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
    heroes: dict[tuple[int, str], dict[str, Any]]


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


def _read_narrative_document(path: Path) -> dict[str, Any]:
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
    if data.get("generator_version") != NARRATIVE_GENERATOR_VERSION:
        raise NarrativeError(f"{path} uses an outdated description generator")
    return data


type _CatalogHeader = tuple[
    str,
    str,
    dict[str, Any],
    dict[str, Any],
    list[int],
    list[Any],
    list[Any],
]


def _catalog_header(path: Path, data: dict[str, Any]) -> _CatalogHeader:
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
    return cast(
        "_CatalogHeader",
        (
            snapshot_id,
            source_context,
            patch,
            cohort,
            requested,
            exclusions,
            entries,
        ),
    )


def _catalog_exclusions(path: Path, exclusions: list[Any]) -> dict[int, str]:
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
    return exclusion_map


def _catalog_heroes(
    path: Path,
    entries: list[Any],
    snapshot_id: str,
) -> dict[tuple[int, str], dict[str, Any]]:
    heroes: dict[tuple[int, str], dict[str, Any]] = {}
    for entry in entries:
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("hero_id"), int)
            or not isinstance(entry.get("path_id"), str)
            or not entry["path_id"].strip()
        ):
            raise NarrativeError(f"{path} contains an invalid hero narrative")
        if entry.get("generator_version") != NARRATIVE_GENERATOR_VERSION:
            raise NarrativeError(
                f"{path} contains a hero from an outdated description generator"
            )
        _require_identity(path, entry, snapshot_id)
        build_key = int(entry["hero_id"]), str(entry["path_id"])
        if build_key in heroes:
            raise NarrativeError(
                f"{path} contains duplicate build {build_key[0]}/{build_key[1]}"
            )
        heroes[build_key] = entry
    return heroes


def _validate_catalog_coverage(
    path: Path,
    heroes: dict[tuple[int, str], dict[str, Any]],
    exclusion_map: dict[int, str],
    requested_ids: set[int],
) -> None:
    hero_ids = {build_key[0] for build_key in heroes}
    if hero_ids & set(exclusion_map):
        raise NarrativeError(f"{path} both includes and excludes a hero")
    if hero_ids | set(exclusion_map) != requested_ids:
        raise NarrativeError(f"{path} does not cover every requested hero")


def load_narrative_catalog(path: Path) -> NarrativeCatalog:
    """Load a complete narrative artifact and validate its compatibility envelope.

    Returns:
        An exact-snapshot catalog ready for deterministic admission.

    """
    data = _read_narrative_document(path)
    (
        snapshot_id,
        source_context,
        patch,
        cohort,
        requested,
        exclusions,
        entries,
    ) = _catalog_header(path, data)
    exclusion_map = _catalog_exclusions(path, exclusions)
    heroes = _catalog_heroes(path, entries, snapshot_id)
    requested_ids = set(requested)
    _validate_catalog_coverage(path, heroes, exclusion_map, requested_ids)
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


def _narrative_entry(
    guide: PurchaseGuide,
    context: dict[str, Any],
    patch: Patch,
    catalog: NarrativeCatalog,
) -> dict[str, Any]:
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
    entry = catalog.heroes.get((guide.hero_id, guide.path_id))
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
    return entry


def apply_narrative(
    guide: PurchaseGuide,
    context: dict[str, Any],
    patch: Patch,
    catalog: NarrativeCatalog,
) -> PurchaseGuide:
    """Admit one build description when its artifact identity is exact.

    Returns:
        A guide with only its player-facing description replaced.

    Raises:
        NarrativeError: If the description is missing or incompatible.

    """
    entry = _narrative_entry(guide, context, patch, catalog)
    description = entry.get("build_description")
    if not isinstance(description, str) or not description.strip():
        raise NarrativeError(f"narrative for {guide.hero_name} is incomplete")
    return replace(guide, summary=description.strip(), tactical_profile=None)


def _sentence(value: object) -> str:
    if not isinstance(value, str):
        return ""
    text = " ".join(value.split()).strip()
    if not text:
        return ""
    return text if text[-1] in ".!?" else text + "."


def _first_maxed_ability(context: dict[str, Any]) -> str:
    policy = context.get("ability_policy")
    steps = policy.get("steps") if isinstance(policy, dict) else None
    if not isinstance(steps, list):
        return ""
    for step in steps:
        if (
            isinstance(step, dict)
            and step.get("action") == "UPGRADE_3"
            and isinstance(step.get("ability"), str)
        ):
            return str(step["ability"]).strip()
    return ""


def deterministic_build_description(context: dict[str, Any]) -> str:
    """Build one stable player-facing description from pinned context fields.

    Returns:
        A complete description with no generated or inferred mechanics.

    Raises:
        NarrativeError: If the context cannot produce bounded useful text.

    """
    hero = str(context.get("hero") or "").strip()
    mechanics = context.get("hero_mechanics")
    descriptions = mechanics.get("description") if isinstance(mechanics, dict) else None
    policy = context.get("policy")
    role = (descriptions.get("role") if isinstance(descriptions, dict) else None) or (
        policy.get("strategic_role") if isinstance(policy, dict) else None
    )
    playstyle = (
        descriptions.get("playstyle") if isinstance(descriptions, dict) else None
    )
    projection = context.get("projection")
    build = projection.get("build") if isinstance(projection, dict) else None
    archetype = build.get("archetype") if isinstance(build, dict) else None
    first_maxed = _first_maxed_ability(context)
    if not hero or not isinstance(role, str) or not role.strip():
        raise NarrativeError("description context has no hero role")

    role_sentence = _sentence(f"{hero}: {role}")
    plan = (
        f"Follow the shown {str(archetype).strip()} CORE order"
        if archetype
        else ("Follow the shown CORE order")
    )
    if first_maxed:
        plan += f" and max {first_maxed} first"
    plan_sentence = _sentence(plan)
    queue_sentence = (
        "Use conditional cards only when their VS line applies; all optional rows "
        "stay outside Queue."
    )
    fixed = [role_sentence, plan_sentence, queue_sentence]
    with_playstyle = [
        role_sentence,
        _sentence(playstyle),
        plan_sentence,
        queue_sentence,
    ]
    description = " ".join(sentence for sentence in with_playstyle if sentence)
    if len(description) > MAXIMUM_BUILD_DESCRIPTION_CHARACTERS:
        description = " ".join(fixed)
    if (
        not MINIMUM_BUILD_DESCRIPTION_CHARACTERS
        <= len(description)
        <= MAXIMUM_BUILD_DESCRIPTION_CHARACTERS
    ):
        raise NarrativeError(
            "deterministic build description is outside its size limit"
        )
    return description
