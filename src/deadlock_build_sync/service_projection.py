from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from .beam_display import attach_beam_ability_names
from .build_tags import BuildTagCatalog, BuildTagError, select_build_tags
from .narratives import apply_narrative
from .purchase_guidance import attach_purchase_guidance
from .renderer import ProjectionIdentity, project_policy_to_guide
from .strategy_context import build_hero_strategy_context

if TYPE_CHECKING:
    from .api import Patch
    from .narratives import NarrativeCatalog
    from .policy import BuildPolicy
    from .purchase_guide import PurchaseGuide
    from .snapshot import SnapshotManifest

from .service_policy import _build_policy
from .service_types import GuideError, _HeroInputs


@dataclass(frozen=True)
class _ProjectionEnvironment:
    assets: list[dict[str, object]]
    manifest: SnapshotManifest
    rank_identity: str
    build_tag_catalog: BuildTagCatalog
    duration_distribution: dict[str, dict[str, float | int]]
    narrative_catalog: NarrativeCatalog | None
    patch: Patch


def _project_hero_guide(
    inputs: _HeroInputs,
    environment: _ProjectionEnvironment,
) -> tuple[PurchaseGuide, BuildPolicy, dict[str, object]]:
    policy, validation = _build_policy(
        inputs,
        environment.assets,
        environment.manifest,
    )
    if inputs.analytic_guide.cohort is not None:
        policy = replace(
            policy,
            evidence=tuple(
                replace(
                    claim,
                    cohort={
                        **claim.cohort,
                        "rank_range": inputs.analytic_guide.cohort.rank_range.as_dict(),
                    },
                )
                for claim in policy.evidence
            ),
        )
    identity = ProjectionIdentity(
        hero_name=inputs.analytic_guide.hero_name,
        hero_class_name=inputs.analytic_guide.hero_class_name,
        client_version=environment.manifest.client_version,
        match_mode=environment.manifest.match_mode.value,
        rank_identity=inputs.analytic_guide.cohort.rank_range.label
        if inputs.analytic_guide.cohort
        else environment.rank_identity,
    )
    projected = project_policy_to_guide(
        policy,
        validation,
        assets=environment.assets,
        identity=identity,
        layout_source=inputs.analytic_guide,
    )
    projected = replace(projected, ability_path=inputs.analytic_guide.ability_path)
    projected = attach_beam_ability_names(projected, inputs.kit)
    projected = attach_purchase_guidance(projected, environment.assets)
    if projected.ability_path is None:
        raise GuideError(f"{projected.hero_name} has no complete ability path")
    try:
        tag_selection = select_build_tags(
            projected.ability_path.ability_ids,
            projected.core_items,
            environment.assets,
            environment.build_tag_catalog,
        )
    except BuildTagError as error:
        raise GuideError(
            f"{projected.hero_name} build tags are invalid: {error}"
        ) from error
    projected = replace(
        projected,
        build_tag_ids=tag_selection.tag_ids,
        build_tag_classes=tag_selection.class_names,
        build_tag_labels=tag_selection.labels,
        build_tag_catalog_sha256=environment.build_tag_catalog.sha256,
        build_archetype=tag_selection.archetype,
        analysis_start_timestamp=environment.manifest.epochs.analysis_start_timestamp,
        as_of_timestamp=environment.manifest.as_of_timestamp,
    )
    analytic = replace(
        inputs.analytic_guide,
        snapshot_id=environment.manifest.snapshot_id,
        policy_id=policy.policy_id,
        client_version=environment.manifest.client_version,
        match_mode=environment.manifest.match_mode.value,
        rank_identity=inputs.analytic_guide.cohort.rank_range.label
        if inputs.analytic_guide.cohort
        else environment.rank_identity,
        analysis_start_timestamp=environment.manifest.epochs.analysis_start_timestamp,
        as_of_timestamp=environment.manifest.as_of_timestamp,
    )
    context = build_hero_strategy_context(
        analytic,
        inputs.hero,
        environment.assets,
        inputs.duration_curve,
        inputs.duration_distribution or environment.duration_distribution,
        kit=inputs.kit,
        ability_timeline=inputs.ability_timeline,
        policy=policy,
        projection=projected,
        matchups=inputs.matchups,
    )
    if environment.narrative_catalog is not None:
        projected = apply_narrative(
            projected,
            context,
            environment.patch,
            environment.narrative_catalog,
        )
    return projected, policy, context


def _project_hero_guides(
    inputs_by_hero: list[_HeroInputs],
    environment: _ProjectionEnvironment,
) -> tuple[list[PurchaseGuide], list[BuildPolicy], list[dict[str, object]]]:
    guides: list[PurchaseGuide] = []
    policies: list[BuildPolicy] = []
    contexts: list[dict[str, object]] = []
    for inputs in inputs_by_hero:
        guide, policy, context = _project_hero_guide(inputs, environment)
        guides.append(guide)
        policies.append(policy)
        contexts.append(context)
    return guides, policies, contexts
