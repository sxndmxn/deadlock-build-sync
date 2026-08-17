from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, cast

from .purchase_guide import (
    TacticalProfile,
    standard_category_description,
    tactical_item_annotation,
)

if TYPE_CHECKING:
    from pathlib import Path

    from .api import Patch
    from .purchase_guide import GuideCategory, GuideItem, PurchaseGuide

NARRATIVE_SCHEMA_VERSION = 6
NARRATIVE_PROMPT_VERSION = 23
DEFAULT_KIT_MODEL = "gpt-5.6-luna"
DEFAULT_SYNTHESIS_MODEL = "gpt-5.6-luna"
_PLAYER_DESCRIPTION_SURFACE = "player.description"
NARRATIVE_FIELD_SURFACES = {
    "build_summary": ("reviewed_guide.summary",),
    "tactical_profile.primary_role": (_PLAYER_DESCRIPTION_SURFACE,),
    "tactical_profile.fight_role": (_PLAYER_DESCRIPTION_SURFACE,),
    "tactical_profile.economy_plan": (_PLAYER_DESCRIPTION_SURFACE,),
    "tactical_profile.ending_duration_interpretation": ("audit.narrative",),
    "action_explanations": ("player.item_hover",),
    "category_summaries": ("audit.narrative",),
}


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
    if data.get("prompt_version") != NARRATIVE_PROMPT_VERSION:
        raise NarrativeError(f"{path} was generated with an outdated tactical prompt")
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
) -> dict[int, dict[str, Any]]:
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
    return heroes


def _validate_catalog_coverage(
    path: Path,
    heroes: dict[int, dict[str, Any]],
    exclusion_map: dict[int, str],
    requested_ids: set[int],
) -> None:
    if set(heroes) & set(exclusion_map):
        raise NarrativeError(f"{path} both includes and excludes a hero")
    if set(heroes) | set(exclusion_map) != requested_ids:
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
    return entry


type _NarrativeContent = tuple[
    str,
    TacticalProfile,
    list[Any],
    list[Any],
]


def _narrative_content(
    entry: dict[str, Any],
    hero_name: str,
) -> _NarrativeContent:
    summary = entry.get("build_summary")
    tactical_profile = entry.get("tactical_profile")
    action_explanations = entry.get("action_explanations")
    category_summaries = entry.get("category_summaries")
    if (
        not isinstance(summary, str)
        or not summary.strip()
        or not isinstance(tactical_profile, dict)
        or not isinstance(action_explanations, list)
        or not isinstance(category_summaries, list)
    ):
        raise NarrativeError(f"narrative for {hero_name} is incomplete")
    profile_fields = {
        field: tactical_profile.get(field)
        for field in ("primary_role", "fight_role", "economy_plan")
    }
    if any(
        not isinstance(value, str) or not value.strip()
        for value in profile_fields.values()
    ):
        raise NarrativeError(f"narrative for {hero_name} has no tactical profile")
    profile = TacticalProfile(
        primary_role=str(profile_fields["primary_role"]).strip(),
        fight_role=str(profile_fields["fight_role"]).strip(),
        economy_plan=str(profile_fields["economy_plan"]).strip(),
    )
    return summary.strip(), profile, action_explanations, category_summaries


def _narrative_categories(
    guide: PurchaseGuide,
    category_summaries: list[Any],
) -> tuple[GuideCategory, ...]:
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
    return tuple(
        replace(
            category,
            description=(
                standard_category_description(category.name) or summaries[category.name]
            ),
        )
        for category in guide.rendered_categories
    )


def _closed_action_explanations(
    context: dict[str, Any],
    action_explanations: list[Any],
    hero_name: str,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    supplied_actions = context.get("explainable_actions")
    if not isinstance(supplied_actions, list):
        raise NarrativeError(
            f"strategy context for {hero_name} has no explainable actions"
        )
    supplied = [action for action in supplied_actions if isinstance(action, dict)]
    explanations = [
        explanation
        for explanation in action_explanations
        if isinstance(explanation, dict)
    ]
    supplied_nodes = [str(action.get("node_id")) for action in supplied]
    explanation_nodes = [str(action.get("node_id")) for action in explanations]
    if (
        len(supplied) != len(supplied_actions)
        or len(explanations) != len(action_explanations)
        or explanation_nodes != supplied_nodes
    ):
        raise NarrativeError(f"narrative for {hero_name} changed the closed action set")
    return supplied, {
        str(explanation["node_id"]): explanation for explanation in explanations
    }


def _annotated_core_items(
    guide: PurchaseGuide,
    categories: tuple[GuideCategory, ...],
    supplied: list[dict[str, Any]],
    explanation_by_node: dict[str, dict[str, Any]],
) -> tuple[tuple[GuideCategory, ...], tuple[GuideItem, ...], tuple[GuideItem, ...]]:
    core_category = next(
        (category for category in categories if category.name == "CORE ITEMS"),
        None,
    )
    if core_category is None:
        core_category = next(
            (category for category in categories if not category.optional),
            None,
        )
    if core_category is None:
        raise NarrativeError(f"projection for {guide.hero_name} has no CORE row")
    core_items = list(guide.core_items or core_category.items)
    core_actions = [
        action
        for action in supplied
        if str(action.get("node_id") or "").startswith("core-")
    ]
    if len(core_actions) != len(core_items):
        raise NarrativeError(
            f"narrative for {guide.hero_name} does not cover every final CORE item"
        )
    annotated_items = []
    for position, (item, action) in enumerate(
        zip(core_items, core_actions, strict=True),
        start=1,
    ):
        node_id = f"core-{position}"
        explanation = explanation_by_node.get(node_id)
        if (
            action.get("node_id") != node_id
            or action.get("action_id") != item.item_id
            or action.get("action") != item.name
            or explanation is None
            or explanation.get("evidence_ref") != action.get("evidence_ref")
            or not isinstance(explanation.get("instruction"), str)
        ):
            raise NarrativeError(
                f"narrative for {guide.hero_name} changed CORE action {node_id}"
            )
        try:
            annotation = tactical_item_annotation(str(explanation["instruction"]), item)
        except ValueError as error:
            raise NarrativeError(
                f"narrative for {guide.hero_name} has invalid CORE action {node_id}: "
                f"{error}"
            ) from error
        annotated_items.append(replace(item, tactical_annotation=annotation))
    annotated_core = tuple(annotated_items)
    annotated_by_id = {item.item_id: item for item in annotated_core}
    annotated_purchase_path = tuple(
        annotated_by_id.get(item.item_id, item) for item in core_category.items
    )
    updated_categories = tuple(
        replace(category, items=annotated_purchase_path)
        if category is core_category
        else category
        for category in categories
    )
    return updated_categories, annotated_core, annotated_purchase_path


def _conditional_annotations(
    categories: tuple[GuideCategory, ...],
    supplied: list[dict[str, Any]],
    explanation_by_node: dict[str, dict[str, Any]],
    hero_name: str,
) -> dict[int, GuideItem]:
    annotations: dict[int, GuideItem] = {}
    for action in supplied:
        if not isinstance(action.get("conditional_contract"), dict):
            continue
        node_id = str(action.get("node_id"))
        explanation = explanation_by_node.get(node_id)
        action_id = action.get("action_id")
        matches = [
            item
            for category in categories
            if category.optional
            for item in category.items
            if item.item_id == action_id
        ]
        if (
            not isinstance(action_id, int)
            or len(matches) != 1
            or action.get("action") != matches[0].name
            or explanation is None
            or explanation.get("evidence_ref") != action.get("evidence_ref")
            or not isinstance(explanation.get("instruction"), str)
        ):
            raise NarrativeError(
                f"narrative for {hero_name} changed conditional action {node_id}"
            )
        try:
            annotation = tactical_item_annotation(
                str(explanation["instruction"]), matches[0]
            )
        except ValueError as error:
            raise NarrativeError(
                f"narrative for {hero_name} has invalid conditional action "
                f"{node_id}: {error}"
            ) from error
        annotations[action_id] = replace(matches[0], tactical_annotation=annotation)
    return annotations


def _apply_conditional_annotations(
    categories: tuple[GuideCategory, ...],
    tiers: dict[int, tuple[GuideItem, ...]],
    annotations: dict[int, GuideItem],
) -> tuple[tuple[GuideCategory, ...], dict[int, tuple[GuideItem, ...]]]:
    if annotations:
        categories = tuple(
            replace(
                category,
                items=tuple(
                    annotations.get(item.item_id, item) for item in category.items
                ),
            )
            for category in categories
        )
    updated_tiers = {
        tier: tuple(annotations.get(item.item_id, item) for item in items)
        for tier, items in tiers.items()
    }
    return categories, updated_tiers


def apply_narrative(
    guide: PurchaseGuide,
    context: dict[str, Any],
    patch: Patch,
    catalog: NarrativeCatalog,
) -> PurchaseGuide:
    """Admit prose only when snapshot, policy, context, and projection are exact.

    Returns:
        A guide with summaries replaced while all executable fields remain unchanged.

    """
    entry = _narrative_entry(guide, context, patch, catalog)
    summary, tactical_profile, action_explanations, category_summaries = (
        _narrative_content(entry, guide.hero_name)
    )
    categories = _narrative_categories(guide, category_summaries)
    supplied, explanation_by_node = _closed_action_explanations(
        context, action_explanations, guide.hero_name
    )
    categories, annotated_core, annotated_purchase_path = _annotated_core_items(
        guide, categories, supplied, explanation_by_node
    )
    optional_annotations = _conditional_annotations(
        categories, supplied, explanation_by_node, guide.hero_name
    )
    categories, tiers = _apply_conditional_annotations(
        categories, guide.tiers, optional_annotations
    )
    return replace(
        guide,
        summary=summary,
        tactical_profile=tactical_profile,
        categories=categories,
        core_items=annotated_core,
        core_purchase_items=annotated_purchase_path,
        tiers=tiers,
    )
