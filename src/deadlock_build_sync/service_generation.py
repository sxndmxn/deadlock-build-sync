from __future__ import annotations

from typing import TYPE_CHECKING

from .artifacts import ArtifactError
from .build_evidence import (
    METHOD_VERSION,
    assert_build_evidence_compatible,
)
from .build_tags import BuildTagCatalog, BuildTagError
from .mechanics import (
    ItemGraph,
    MechanicsError,
)
from .snapshot import EvidenceUnit
from .strategy_context import build_item_mechanics_catalog
from .value_validation import integer, object_list

if TYPE_CHECKING:
    from .api import DeadlockApi
    from .build_evidence import (
        BuildEvidenceCatalog,
    )
    from .narratives import NarrativeCatalog

from .service_inputs import (
    _collect_hero_inputs,
    _GenerationEvidence,
    _matchups_by_hero,
)
from .service_projection import _project_hero_guides, _ProjectionEnvironment
from .service_types import (
    GeneratedGuides,
    GuideError,
    _duration_distribution,
    _rank_identity,
    select_heroes,
)


def generate_guides(
    api: DeadlockApi,
    *,
    build_evidence: BuildEvidenceCatalog,
    account_id: int,
    hero_query: str | None,
    all_heroes: bool,
    narrative_catalog: NarrativeCatalog | None = None,
) -> GeneratedGuides:
    client_version = api.resolve_client_version()
    rank_catalog = api.rank_catalog()
    heroes = api.active_heroes()
    selected = select_heroes(heroes, hero_query=hero_query, all_heroes=all_heroes)
    assets = api.items()
    try:
        build_tag_catalog = BuildTagCatalog.from_assets(api.build_tags())
    except BuildTagError as error:
        raise GuideError(f"pinned build-tag taxonomy is invalid: {error}") from error
    try:
        item_graph = ItemGraph.from_assets(assets)
    except MechanicsError as error:
        raise GuideError(f"pinned item mechanics are invalid: {error}") from error
    _ = item_graph
    patch = api.current_patch()
    try:
        assert_build_evidence_compatible(
            build_evidence,
            patch_identity=patch.identity,
            client_version=client_version,
            as_of_timestamp=api.as_of_timestamp,
            match_mode=api.match_mode,
            rank_range=api.rank_range,
            rank_catalog=rank_catalog,
            heroes=heroes,
            assets=assets,
            epochs=api.epochs_for_patch(patch),
        )
    except ArtifactError as error:
        raise GuideError(str(error)) from error
    api.recorder.declare(
        "artifact:build-evidence",
        unit=EvidenceUnit.ELIGIBLE_APPEARANCE,
        backend_grain="reconstructed-final-inventory-and-first-ownership",
        fallback_behavior="reject; no aggregate-API approximation",
    )
    api.recorder.record(
        "artifact:build-evidence",
        {
            "artifact_id": build_evidence.artifact_id,
            "method": METHOD_VERSION,
            "hero_count": len(build_evidence.heroes),
        },
        build_evidence.raw_bytes,
    )
    analysis_start = api.analysis_start_timestamp(patch)
    duration_curves = api.hero_stats_by_duration(min_unix_timestamp=analysis_start)
    duration_distribution = _duration_distribution(heroes, duration_curves)
    same_lane_matchups = _matchups_by_hero(
        api.hero_counter_stats(
            min_unix_timestamp=analysis_start,
            same_lane=True,
        ),
        scope="same_lane",
    )
    whole_team_matchups = _matchups_by_hero(
        api.hero_counter_stats(
            min_unix_timestamp=analysis_start,
            same_lane=False,
        ),
        scope="whole_enemy_team",
    )
    persona = api.steam_persona(account_id)

    generation_evidence = _GenerationEvidence(
        assets,
        build_evidence,
        analysis_start,
        duration_curves,
        same_lane_matchups,
        whole_team_matchups,
    )
    inputs_by_hero, skipped_heroes, exclusions = _collect_hero_inputs(
        api,
        selected,
        generation_evidence,
        all_heroes=all_heroes,
    )

    manifest = api.snapshot_manifest(
        patch=patch,
        rank_catalog=rank_catalog,
        build_tags_sha256=build_tag_catalog.sha256,
    )
    rank_identity = _rank_identity(rank_catalog, api.rank_range)
    projection_environment = _ProjectionEnvironment(
        assets,
        manifest,
        rank_identity,
        build_tag_catalog,
        duration_distribution,
        narrative_catalog,
        patch,
    )
    guides, policies, contexts = _project_hero_guides(
        inputs_by_hero, projection_environment
    )

    return GeneratedGuides(
        guides=guides,
        policies=policies,
        contexts=contexts,
        item_mechanics=build_item_mechanics_catalog(
            assets,
            {
                item_id
                for context in contexts
                for item_id in object_list(context.get("item_mechanics_ids")) or []
                if isinstance(item_id, int)
            },
        ),
        skipped_heroes=tuple(skipped_heroes),
        exclusions=tuple(exclusions),
        eligible_hero_ids=frozenset(integer(hero["id"]) for hero in heroes),
        subset_selected=not all_heroes,
        rank_range=api.rank_range,
        rank_catalog=rank_catalog,
        persona=persona,
        patch=patch,
        manifest=manifest,
    )
