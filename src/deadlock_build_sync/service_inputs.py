from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .ability_order import LOW_ABILITY_DECISION_SUPPORT, select_ability_path
from .artifacts import ArtifactError
from .build_evidence import (
    select_hero_build,
)
from .mechanics import (
    AbilityDefinition,
    MechanicsError,
    ability_definitions_from_kit,
    build_hero_mechanics,
    schedule_ability_path,
    validate_ability_timeline,
)
from .purchase_guide import (
    build_purchase_guide_from_evidence,
)
from .value_validation import integer

if TYPE_CHECKING:
    from .ability_order import AbilityPath
    from .api import DeadlockApi, HeroDurationStat
    from .build_evidence import (
        BuildEvidenceCatalog,
        SelectedHeroBuild,
    )

from .service_types import (
    GuideError,
    _handle_incomplete_analytics,
    _HeroInputs,
)


def _matchups_by_hero(
    rows: list[dict[str, object]],
    *,
    scope: str,
) -> dict[int, list[dict[str, object]]]:
    grouped: dict[int, list[dict[str, object]]] = {}
    for row in rows:
        hero_id = row.get("hero_id")
        enemy_hero_id = row.get("enemy_hero_id")
        if not isinstance(hero_id, int) or not isinstance(enemy_hero_id, int):
            continue
        grouped.setdefault(hero_id, []).append({
            **row,
            "scope": scope,
            "unit": "hero_enemy_pair",
        })
    return grouped


@dataclass(frozen=True)
class _GenerationEvidence:
    assets: list[dict[str, object]]
    build_evidence: BuildEvidenceCatalog
    analysis_start: int
    duration_curves: dict[int, tuple[HeroDurationStat, ...]]
    same_lane_matchups: dict[int, list[dict[str, object]]]
    whole_team_matchups: dict[int, list[dict[str, object]]]


def _ability_path_for_build(
    api: DeadlockApi,
    *,
    hero_id: int,
    analysis_start: int,
    selected_build: SelectedHeroBuild,
    global_path: AbilityPath,
    use_item_filter: bool,
) -> AbilityPath:
    if not use_item_filter:
        return global_path
    filter_item_ids = tuple(item.item_id for item in selected_build.backbone)
    filtered_rows = api.ability_order_stats(
        hero_id=hero_id,
        min_unix_timestamp=analysis_start,
        min_matches=1,
        include_item_ids=filter_item_ids,
    )
    filtered_path = select_ability_path(
        filtered_rows,
        filter_item_ids=filter_item_ids,
    )
    if (
        filtered_path is not None
        and filtered_path.minimum_decision_support >= LOW_ABILITY_DECISION_SUPPORT
    ):
        return filtered_path
    return global_path


def _invalid_imbue_target(
    selected_build: SelectedHeroBuild,
    definitions: dict[int, AbilityDefinition],
) -> str | None:
    """Return the first telemetry target that is not in the current hero kit.

    Returns:
        A validation failure, or ``None`` when every target is current.

    """
    items = (
        *selected_build.core,
        *selected_build.core_purchase_path,
        *selected_build.optional_core,
        *(item for tier in selected_build.tiers.values() for item in tier),
    )
    checked: set[int] = set()
    for item in items:
        if item.item_id in checked:
            continue
        checked.add(item.item_id)
        target_id = item.imbue_target_ability_id
        if target_id is not None and target_id not in definitions:
            return (
                f"item {item.item} has observed imbue target {target_id}, "
                "which is not a current hero ability"
            )
    return None


def _prepare_hero_inputs(
    api: DeadlockApi,
    hero: dict[str, object],
    evidence: _GenerationEvidence,
) -> tuple[_HeroInputs, ...] | str:
    hero_id = integer(hero["id"])
    hero_name = str(hero.get("name") or hero_id)
    global_ability_rows = api.ability_order_stats(
        hero_id=hero_id,
        min_unix_timestamp=evidence.analysis_start,
        min_matches=1,
    )
    global_ability_path = select_ability_path(global_ability_rows)
    if global_ability_path is None:
        return "a complete reached-state ability projection"
    hero_builds = evidence.build_evidence.hero_builds.get(
        hero_id,
        (evidence.build_evidence.heroes[hero_id],),
    )
    duration_curve = evidence.duration_curves.get(hero_id, ())
    try:
        kit = build_hero_mechanics(hero, evidence.assets)
        definitions = ability_definitions_from_kit(kit)
    except MechanicsError as error:
        return f"complete current mechanics: {error}"
    prepared: list[_HeroInputs] = []
    for build_evidence in hero_builds:
        try:
            selected_build = select_hero_build(build_evidence, evidence.assets)
        except (ArtifactError, KeyError) as error:
            raise GuideError(
                f"{hero_name} path {build_evidence.path_id} has invalid build "
                f"evidence: {error}"
            ) from error
        invalid_imbue = _invalid_imbue_target(selected_build, definitions)
        if invalid_imbue is not None:
            return f"path {build_evidence.path_label} with valid imbue data: {invalid_imbue}"
        ability_path = _ability_path_for_build(
            api,
            hero_id=hero_id,
            analysis_start=evidence.analysis_start,
            selected_build=selected_build,
            global_path=global_ability_path,
            use_item_filter=len(hero_builds) > 1,
        )
        analytic_guide = build_purchase_guide_from_evidence(
            hero,
            selected_build,
            ability_path=ability_path,
        )
        if not analytic_guide.has_complete_item_coverage:
            return (
                f"path {build_evidence.path_label} needs at least one supported "
                "item action in every tier"
            )
        try:
            actions = schedule_ability_path(
                definitions,
                kit.get("level_info"),
                ability_path.ability_ids,
            )
            timeline = validate_ability_timeline(
                definitions,
                kit.get("level_info"),
                actions,
            )
        except MechanicsError as error:
            return f"complete current mechanics: {error}"
        prepared.append(
            _HeroInputs(
                hero,
                analytic_guide,
                kit,
                timeline,
                duration_curve,
                {
                    "same_lane": evidence.same_lane_matchups.get(hero_id, []),
                    "whole_enemy_team": evidence.whole_team_matchups.get(hero_id, []),
                },
                build_evidence.situational_policy,
            )
        )
    return tuple(prepared)


def _collect_hero_inputs(
    api: DeadlockApi,
    selected: list[dict[str, object]],
    evidence: _GenerationEvidence,
    *,
    all_heroes: bool,
) -> tuple[list[_HeroInputs], list[str], list[tuple[int, str]]]:
    inputs_by_hero: list[_HeroInputs] = []
    skipped_heroes: list[str] = []
    exclusions: list[tuple[int, str]] = []
    for hero in selected:
        prepared = _prepare_hero_inputs(api, hero, evidence)
        if isinstance(prepared, str):
            hero_id = integer(hero["id"])
            _handle_incomplete_analytics(
                all_heroes=all_heroes,
                skipped_heroes=skipped_heroes,
                exclusions=exclusions,
                hero_id=hero_id,
                hero_name=str(hero.get("name") or hero_id),
                reason=prepared,
            )
            continue
        inputs_by_hero.extend(prepared)
    return inputs_by_hero, skipped_heroes, exclusions
