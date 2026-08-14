from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from .ability_order import LOW_ABILITY_DECISION_SUPPORT, select_ability_path
from .artifacts import ArtifactError
from .build_evidence import (
    MECHANIC_RESPONSE_THREATS,
    METHOD_VERSION,
    assert_build_evidence_compatible,
    select_hero_build,
)
from .build_tags import BuildTagCatalog, BuildTagError, select_build_tags
from .item_jobs import annotate_optional_items
from .mechanics import (
    AbilityTimelineStep,
    ItemGraph,
    MechanicsError,
    ability_definitions_from_kit,
    build_hero_mechanics,
    classify_item_threat_responses,
    schedule_ability_path,
    validate_ability_timeline,
)
from .narratives import NarrativeCatalog, apply_narrative
from .policy import (
    Abstention,
    AbstentionReason,
    Branch,
    BuildPolicy,
    ClaimClass,
    CounterCard,
    EvidenceClaim,
    Guard,
    GuardOperator,
    NodeKind,
    PolicyNode,
    ValidationContext,
)
from .power_curve import (
    summarize_duration_distribution,
    summarize_ending_duration_profile,
)
from .purchase_guide import (
    MAX_TACTICAL_INSTRUCTION_BYTES,
    PurchaseGuide,
    build_purchase_guide_from_evidence,
)
from .renderer import ProjectionIdentity, project_policy_to_guide
from .snapshot import EvidenceUnit
from .strategy_context import build_hero_strategy_context

if TYPE_CHECKING:
    from .api import DeadlockApi, HeroDurationStat, Patch
    from .build_evidence import (
        BuildEvidenceCatalog,
        SituationalBranch,
        SituationalPolicy,
    )
    from .ranks import RankCatalog, RankRange
    from .snapshot import SnapshotManifest


class GuideError(RuntimeError):
    """Raised when analytics cannot produce a usable guide."""


@dataclass(frozen=True)
class GeneratedGuides:
    guides: list[PurchaseGuide]
    policies: list[BuildPolicy]
    contexts: list[dict[str, Any]]
    skipped_heroes: tuple[str, ...]
    exclusions: tuple[tuple[int, str], ...]
    eligible_hero_ids: frozenset[int]
    subset_selected: bool
    rank_range: RankRange
    rank_catalog: RankCatalog
    persona: str
    patch: Patch
    manifest: SnapshotManifest


@dataclass(frozen=True)
class _HeroInputs:
    hero: dict[str, Any]
    analytic_guide: PurchaseGuide
    kit: dict[str, Any]
    ability_timeline: tuple[AbilityTimelineStep, ...]
    duration_curve: tuple[HeroDurationStat, ...]
    matchups: dict[str, list[dict[str, Any]]]
    situational_policy: SituationalPolicy | None


def _handle_incomplete_analytics(
    *,
    all_heroes: bool,
    skipped_heroes: list[str],
    exclusions: list[tuple[int, str]],
    hero_id: int,
    hero_name: str,
    reason: str,
) -> None:
    if all_heroes:
        skipped_heroes.append(f"{hero_name} ({reason})")
        exclusions.append((hero_id, reason))
        return
    raise GuideError(f"{hero_name} did not have {reason}")


def _duration_distribution(
    heroes: list[dict[str, Any]],
    curves: dict[int, tuple[HeroDurationStat, ...]],
) -> dict[str, dict[str, float | int]]:
    active_hero_ids = {int(hero["id"]) for hero in heroes}
    return summarize_duration_distribution({
        hero_id: points
        for hero_id, points in curves.items()
        if hero_id in active_hero_ids
    })


def select_heroes(
    heroes: list[dict[str, Any]],
    *,
    hero_query: str | None,
    all_heroes: bool,
) -> list[dict[str, Any]]:
    if all_heroes:
        return heroes
    if not hero_query:
        raise GuideError("pass --hero NAME or --all")
    normalized = hero_query.casefold().replace(" ", "").replace("&", "and")
    matches = []
    for hero in heroes:
        candidates = {
            str(hero.get("id") or ""),
            str(hero.get("name") or "").casefold().replace(" ", "").replace("&", "and"),
            str(hero.get("class_name") or "").casefold().removeprefix("hero_"),
        }
        if normalized in candidates:
            matches.append(hero)
    if not matches:
        raise GuideError(f"active hero not found: {hero_query}")
    if len(matches) > 1:
        names = ", ".join(str(hero.get("name")) for hero in matches)
        raise GuideError(f"hero query is ambiguous: {names}")
    return matches


def _rank_identity(catalog: RankCatalog, rank_range: RankRange) -> str:
    minimum = rank_range.minimum
    maximum = rank_range.maximum
    if minimum == maximum:
        return f"{catalog.label(minimum)} [{minimum.badge_id}]"
    return (
        f"{catalog.label(minimum)} [{minimum.badge_id}]–"
        f"{catalog.label(maximum)} [{maximum.badge_id}]"
    )


def _cohort(manifest: SnapshotManifest) -> dict[str, Any]:
    return {
        "match_mode": manifest.match_mode.value,
        "game_mode": manifest.game_mode,
        "rank_range": manifest.rank_range,
        "as_of_timestamp": manifest.as_of_timestamp,
        "epochs": manifest.epochs.as_dict(),
    }


def _mechanical_claim(
    *,
    claim_id: str,
    mechanics_ref: str,
    manifest: SnapshotManifest,
) -> EvidenceClaim:
    return EvidenceClaim(
        claim_id=claim_id,
        claim_class=ClaimClass.MECHANICAL,
        snapshot_id=manifest.snapshot_id,
        cohort=_cohort(manifest),
        unit=EvidenceUnit.ASSET,
        support=1,
        mechanics_refs=(mechanics_ref,),
        language_ceiling=frozenset({"grants", "requires", "can target"}),
    )


def _item_claim(
    item: Any,
    *,
    manifest: SnapshotManifest,
) -> EvidenceClaim:
    return EvidenceClaim(
        claim_id=f"item/{item.item_id}/adoption",
        claim_class=ClaimClass.DESCRIPTIVE,
        snapshot_id=manifest.snapshot_id,
        cohort=_cohort(manifest),
        unit=EvidenceUnit.ELIGIBLE_APPEARANCE,
        support=item.eligible_player_matches,
        mechanics_refs=(f"item/{item.item_id}",),
        language_ceiling=frozenset({"observed", "adopted", "rate", "more common"}),
        numerator=item.adopter_matches,
        denominator=item.eligible_player_matches,
        estimate=item.purchase_adoption,
        comparison_baseline=None,
    )


def _core_claim(guide: PurchaseGuide, manifest: SnapshotManifest) -> EvidenceClaim:
    return EvidenceClaim(
        claim_id=f"hero/{guide.hero_id}/coherent-eight-item-core",
        claim_class=ClaimClass.DESCRIPTIVE,
        snapshot_id=manifest.snapshot_id,
        cohort=_cohort(manifest),
        unit=EvidenceUnit.ELIGIBLE_APPEARANCE,
        support=guide.core_items[0].eligible_player_matches,
        mechanics_refs=tuple(f"item/{item.item_id}" for item in guide.core_items),
        language_ceiling=frozenset({"observed", "adopted", "rate", "more common"}),
        numerator=guide.core_joint_matches,
        denominator=guide.core_items[0].eligible_player_matches,
        estimate=guide.core_joint_share,
    )


def _situational_claim(
    branch: SituationalBranch,
    *,
    hero_id: int,
    manifest: SnapshotManifest,
) -> EvidenceClaim:
    enemy = branch.enemy_hero_id if branch.enemy_hero_id is not None else "any"
    return EvidenceClaim(
        claim_id=(
            f"hero/{hero_id}/situational/{branch.threat}/{enemy}/{branch.item_id}"
        ),
        claim_class=ClaimClass.DESCRIPTIVE,
        snapshot_id=manifest.snapshot_id,
        cohort=_cohort(manifest),
        unit=EvidenceUnit.HERO_ENEMY_PAIR,
        support=branch.support,
        mechanics_refs=(branch.mechanic_ref,),
        language_ceiling=frozenset({"observed", "associated"}),
        estimate=sum(branch.comparative_interval) / 2,
        interval=branch.comparative_interval,
        comparison_baseline=0.0,
    )


def _situational_annotation(
    branch: SituationalBranch,
    *,
    assets_by_id: dict[int, dict[str, Any]],
    hero_names: dict[int, str],
) -> str:
    item = str(
        assets_by_id.get(branch.item_id, {}).get("name") or f"item {branch.item_id}"
    )
    comparator = str(
        assets_by_id.get(branch.comparator_item_id, {}).get("name")
        or f"item {branch.comparator_item_id}"
    )
    threat = branch.threat.replace("_", " ")
    enemy = (
        hero_names.get(branch.enemy_hero_id, f"enemy {branch.enemy_hero_id}")
        if branch.enemy_hero_id is not None
        else "the enemy"
    )
    annotation = (
        f"If {enemy}'s {threat} is material, choose {item} over {comparator}; "
        "use its verified response while observed; skip if threat or timing changes."
    )
    if len(annotation.encode("utf-8")) > MAX_TACTICAL_INSTRUCTION_BYTES:
        raise GuideError(
            f"situational annotation for item {branch.item_id} exceeds "
            f"{MAX_TACTICAL_INSTRUCTION_BYTES} UTF-8 bytes"
        )
    return annotation


def _build_policy(
    inputs: _HeroInputs,
    assets: list[dict[str, Any]],
    hero_names: dict[int, str],
    manifest: SnapshotManifest,
) -> tuple[BuildPolicy, ValidationContext]:
    guide = inputs.analytic_guide
    definitions = ability_definitions_from_kit(inputs.kit)
    item_graph = ItemGraph.from_assets(assets)
    validation = ValidationContext(
        item_graph=item_graph,
        ability_definitions=definitions,
        level_info=inputs.kit.get("level_info"),
    )
    if len(guide.core_items) != 8:
        raise GuideError(f"{guide.hero_name} does not have an eight-item core")
    evidence: dict[str, EvidenceClaim] = {}
    item_claims = {
        item.item_id: _item_claim(item, manifest=manifest)
        for tier_items in guide.tiers.values()
        for item in tier_items
    }
    evidence.update((claim.claim_id, claim) for claim in item_claims.values())
    core_claim = _core_claim(guide, manifest)
    evidence[core_claim.claim_id] = core_claim
    for ability_id in definitions:
        claim = _mechanical_claim(
            claim_id=f"ability/{ability_id}/mechanics",
            mechanics_ref=f"ability/{ability_id}",
            manifest=manifest,
        )
        evidence[claim.claim_id] = claim

    purchase_nodes = tuple(
        PolicyNode(
            f"core-{position}",
            NodeKind.PURCHASE,
            next_id=f"core-{position + 1}" if position < 8 else "end",
            evidence_ref=core_claim.claim_id,
            item_id=item.item_id,
        )
        for position, item in enumerate(guide.core_items, start=1)
    )
    assets_by_id = {
        int(asset["id"]): asset for asset in assets if isinstance(asset.get("id"), int)
    }
    situational_branches = (
        inputs.situational_policy.branches
        if inputs.situational_policy is not None
        else ()
    )
    conditional_branches: list[Branch] = []
    conditional_purchases: list[PolicyNode] = []
    counter_cards: list[CounterCard] = []
    for position, branch in enumerate(situational_branches, start=1):
        if branch.item_id in {item.item_id for item in guide.core_items}:
            raise GuideError(
                f"{guide.hero_name} situational item {branch.item_id} repeats CORE"
            )
        if (
            branch.item_id not in assets_by_id
            or branch.comparator_item_id not in assets_by_id
        ):
            raise GuideError(
                f"{guide.hero_name} situational branch references missing assets"
            )
        response = branch.mechanic_ref.rsplit("/", 1)[-1]
        if (
            response not in classify_item_threat_responses(assets_by_id[branch.item_id])
            or MECHANIC_RESPONSE_THREATS.get(response) != branch.threat
        ):
            raise GuideError(
                f"{guide.hero_name} situational item {branch.item_id} lacks its "
                "claimed response mechanic"
            )
        claim = _situational_claim(
            branch,
            hero_id=guide.hero_id,
            manifest=manifest,
        )
        evidence[claim.claim_id] = claim
        purchase_id = f"situational-{position}"
        guards = [Guard("enemy.threats", GuardOperator.CONTAINS, branch.threat)]
        if branch.enemy_hero_id is not None:
            guards.append(
                Guard(
                    "enemy.heroes",
                    GuardOperator.CONTAINS,
                    branch.enemy_hero_id,
                )
            )
        annotation = _situational_annotation(
            branch,
            assets_by_id=assets_by_id,
            hero_names=hero_names,
        )
        conditional_branches.append(
            Branch(
                purchase_id,
                guards[0],
                additional_guards=tuple(guards[1:]),
            )
        )
        conditional_purchases.append(
            PolicyNode(
                purchase_id,
                NodeKind.PURCHASE,
                next_id="core-1",
                evidence_ref=claim.claim_id,
                item_id=branch.item_id,
                optional=True,
                annotation=annotation,
            )
        )
        counter_cards.append(
            CounterCard(
                threat=branch.threat,
                item_id=branch.item_id,
                comparator_item_id=branch.comparator_item_id,
                mechanic_ref=branch.mechanic_ref,
                legal_timing="same observed decision opportunity",
                alternative=branch.comparator,
                replacement=branch.replacement,
                execution_mode=branch.execution,
                failure_condition=branch.failure_condition,
                evidence_ref=claim.claim_id,
                enemy_hero_id=branch.enemy_hero_id,
            )
        )

    path = guide.ability_path
    if path is None:
        raise GuideError(f"{guide.hero_name} has no ability prefix policy")
    ability_nodes: list[PolicyNode] = []
    for position, (ability_id, scheduled) in enumerate(
        zip(path.ability_ids, inputs.ability_timeline, strict=True),
        start=1,
    ):
        node_id = f"ability-{position}"
        ability_nodes.append(
            PolicyNode(
                node_id,
                NodeKind.ABILITY,
                evidence_ref=f"ability/{ability_id}/mechanics",
                ability_id=ability_id,
                level=scheduled.level,
            )
        )
    description = inputs.kit.get("description")
    role = "evidence-grounded default"
    if isinstance(description, dict) and isinstance(description.get("role"), str):
        role = description["role"]
    situational_nodes = (
        (
            PolicyNode(
                "situational-choice",
                NodeKind.CHOICE,
                branches=(*conditional_branches, Branch("core-1")),
            ),
            *conditional_purchases,
        )
        if situational_branches
        else ()
    )
    nodes = (*purchase_nodes, *situational_nodes, PolicyNode("end", NodeKind.END))
    abstentions = [
        Abstention(
            AbstentionReason.INADEQUATE_SUPPORT,
            "Observed first-ownership net-worth distributions are descriptive; no causal or universally optimal buy window is emitted.",
        ),
        Abstention(
            AbstentionReason.INADEQUATE_SUPPORT,
            "No joint item-and-ability acquisition state is available; no empirical power-spike claim is emitted.",
        ),
        Abstention(
            AbstentionReason.TELEMETRY_FAILURE,
            "Observed adopter outcomes are descriptive associations and never select or order an item.",
        ),
    ]
    if situational_branches:
        abstentions.extend(
            Abstention(AbstentionReason.INADEQUATE_SUPPORT, detail)
            for detail in (
                inputs.situational_policy.abstentions
                if inputs.situational_policy is not None
                else ()
            )
        )
    else:
        abstentions.extend((
            Abstention(
                AbstentionReason.UNCLEAR_THREAT,
                "Tier rows are high-adoption reference menus; adoption alone does not identify a situational trigger or counter purchase.",
            ),
            Abstention(
                AbstentionReason.UNCLEAR_THREAT,
                "Raw matchup pairs do not prove a mechanics-first counter pick; enemy-specific counter claims are withheld.",
            ),
        ))
    minimum_ability_support = min(path.decision_support, default=0)
    if minimum_ability_support < LOW_ABILITY_DECISION_SUPPORT:
        abstentions.append(
            Abstention(
                AbstentionReason.INADEQUATE_SUPPORT,
                f"The compact ability projection reaches a sparse legal state with support {minimum_ability_support}; treat its tail as a low-confidence default, not a universal path.",
            )
        )
    if summarize_ending_duration_profile(inputs.duration_curve) is None:
        abstentions.append(
            Abstention(
                AbstentionReason.INADEQUATE_SUPPORT,
                "The frozen cohort lacks a complete supported ending-duration profile; no phase-strength claim is emitted.",
            )
        )
    policy = BuildPolicy(
        schema_version=1,
        hero_id=guide.hero_id,
        variant="coherent-eight-item-core",
        invariant_kit_id=str(inputs.kit["mechanics_sha256"]),
        strategic_role=role,
        snapshot_id=manifest.snapshot_id,
        entry="situational-choice" if situational_branches else "core-1",
        nodes=nodes,
        evidence=tuple(sorted(evidence.values(), key=lambda claim: claim.claim_id)),
        ability_plan=tuple(ability_nodes),
        abstentions=tuple(abstentions),
        counter_cards=tuple(counter_cards),
    )
    return policy, validation


def _normalized_matchups(
    same_lane: list[dict[str, Any]],
    whole_team: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    return {
        "same_lane": [
            {**row, "scope": "same_lane", "unit": "hero_enemy_pair"}
            for row in same_lane
        ],
        "whole_enemy_team": [
            {**row, "scope": "whole_enemy_team", "unit": "hero_enemy_pair"}
            for row in whole_team
        ],
    }


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
    persona = api.steam_persona(account_id)

    inputs_by_hero: list[_HeroInputs] = []
    skipped_heroes: list[str] = []
    exclusions: list[tuple[int, str]] = []
    for hero in selected:
        hero_id = int(hero["id"])
        hero_name = str(hero.get("name") or hero_id)
        ability_rows = api.ability_order_stats(
            hero_id=hero_id,
            min_unix_timestamp=analysis_start,
            min_matches=1,
        )
        same_lane = api.hero_counter_stats(
            hero_id=hero_id,
            min_unix_timestamp=analysis_start,
            same_lane=True,
        )
        whole_team = api.hero_counter_stats(
            hero_id=hero_id,
            min_unix_timestamp=analysis_start,
            same_lane=False,
        )
        ability_path = select_ability_path(ability_rows)
        try:
            selected_build = select_hero_build(build_evidence.heroes[hero_id], assets)
        except (ArtifactError, KeyError) as error:
            raise GuideError(
                f"{hero_name} has invalid build evidence: {error}"
            ) from error
        analytic_guide = build_purchase_guide_from_evidence(
            hero, selected_build, ability_path=ability_path
        )
        if not analytic_guide.has_complete_item_coverage:
            _handle_incomplete_analytics(
                all_heroes=all_heroes,
                skipped_heroes=skipped_heroes,
                exclusions=exclusions,
                hero_id=hero_id,
                hero_name=hero_name,
                reason="at least one supported item action in every tier",
            )
            continue
        if ability_path is None:
            _handle_incomplete_analytics(
                all_heroes=all_heroes,
                skipped_heroes=skipped_heroes,
                exclusions=exclusions,
                hero_id=hero_id,
                hero_name=hero_name,
                reason="a complete reached-state ability projection",
            )
            continue
        duration_curve = duration_curves.get(hero_id, ())
        try:
            kit = build_hero_mechanics(hero, assets)
            definitions = ability_definitions_from_kit(kit)
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
            _handle_incomplete_analytics(
                all_heroes=all_heroes,
                skipped_heroes=skipped_heroes,
                exclusions=exclusions,
                hero_id=hero_id,
                hero_name=hero_name,
                reason=f"complete current mechanics: {error}",
            )
            continue
        inputs_by_hero.append(
            _HeroInputs(
                hero,
                analytic_guide,
                kit,
                timeline,
                duration_curve,
                _normalized_matchups(same_lane, whole_team),
                build_evidence.heroes[hero_id].situational_policy,
            )
        )

    manifest = api.snapshot_manifest(
        patch=patch,
        rank_catalog=rank_catalog,
        build_tags_sha256=build_tag_catalog.sha256,
    )
    rank_identity = _rank_identity(rank_catalog, api.rank_range)
    guides: list[PurchaseGuide] = []
    policies: list[BuildPolicy] = []
    contexts: list[dict[str, Any]] = []
    hero_names = {
        int(hero["id"]): str(hero.get("name") or hero["id"]) for hero in heroes
    }
    for inputs in inputs_by_hero:
        policy, validation = _build_policy(inputs, assets, hero_names, manifest)
        identity = ProjectionIdentity(
            hero_name=inputs.analytic_guide.hero_name,
            hero_class_name=inputs.analytic_guide.hero_class_name,
            client_version=manifest.client_version,
            match_mode=manifest.match_mode.value,
            rank_identity=rank_identity,
        )
        projected = project_policy_to_guide(
            policy,
            validation,
            assets=assets,
            identity=identity,
            layout_source=inputs.analytic_guide,
        )
        projected = replace(projected, ability_path=inputs.analytic_guide.ability_path)
        projected = annotate_optional_items(projected, assets)
        try:
            tag_selection = select_build_tags(
                tuple(item.item_id for item in projected.core_items),
                assets,
                build_tag_catalog,
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
            build_tag_catalog_sha256=build_tag_catalog.sha256,
            build_archetype=tag_selection.archetype,
            as_of_timestamp=manifest.as_of_timestamp,
        )
        analytic = replace(
            inputs.analytic_guide,
            snapshot_id=manifest.snapshot_id,
            policy_id=policy.policy_id,
            client_version=manifest.client_version,
            match_mode=manifest.match_mode.value,
            rank_identity=rank_identity,
        )
        context = build_hero_strategy_context(
            analytic,
            inputs.hero,
            assets,
            inputs.duration_curve,
            duration_distribution,
            kit=inputs.kit,
            ability_timeline=inputs.ability_timeline,
            policy=policy,
            projection=projected,
            matchups=inputs.matchups,
        )
        if narrative_catalog is not None:
            projected = apply_narrative(projected, context, patch, narrative_catalog)
        guides.append(projected)
        policies.append(policy)
        contexts.append(context)

    return GeneratedGuides(
        guides=guides,
        policies=policies,
        contexts=contexts,
        skipped_heroes=tuple(skipped_heroes),
        exclusions=tuple(exclusions),
        eligible_hero_ids=frozenset(int(hero["id"]) for hero in heroes),
        subset_selected=not all_heroes,
        rank_range=api.rank_range,
        rank_catalog=rank_catalog,
        persona=persona,
        patch=patch,
        manifest=manifest,
    )
