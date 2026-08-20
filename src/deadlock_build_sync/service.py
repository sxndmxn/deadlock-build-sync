from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from .ability_order import LOW_ABILITY_DECISION_SUPPORT, select_ability_path
from .artifacts import ArtifactError
from .build_evidence import (
    MAXIMUM_CORE_ITEM_COUNT,
    MECHANIC_RESPONSE_THREATS,
    METHOD_VERSION,
    MINIMUM_BACKBONE_ITEM_COUNT,
    assert_build_evidence_compatible,
    select_hero_build,
)
from .build_tags import BuildTagCatalog, BuildTagError, select_build_tags
from .mechanics import (
    AbilityDefinition,
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
    CoreAlternativeCard,
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
from .strategy_context import build_hero_strategy_context, build_item_mechanics_catalog

if TYPE_CHECKING:
    from .ability_order import AbilityPath
    from .api import DeadlockApi, HeroDurationStat, Patch
    from .build_evidence import (
        BuildEvidenceCatalog,
        SelectedHeroBuild,
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
    item_mechanics: dict[str, dict[str, Any]]
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
        claim_id=f"hero/{guide.hero_id}/stable-supported-backbone",
        claim_class=ClaimClass.DESCRIPTIVE,
        snapshot_id=manifest.snapshot_id,
        cohort=_cohort(manifest),
        unit=EvidenceUnit.ELIGIBLE_APPEARANCE,
        support=guide.core_items[0].eligible_player_matches,
        mechanics_refs=tuple(f"item/{item.item_id}" for item in guide.backbone_items),
        language_ceiling=frozenset({"observed", "adopted", "rate", "more common"}),
        numerator=guide.backbone_matches,
        denominator=guide.core_items[0].eligible_player_matches,
        estimate=guide.backbone_share,
    )


def _core_alternative_claim(
    guide: PurchaseGuide,
    alternative: Any,
    manifest: SnapshotManifest,
) -> EvidenceClaim:
    return EvidenceClaim(
        claim_id=(
            f"hero/{guide.hero_id}/core-alternative/"
            f"{alternative.item_id}-for-{alternative.comparator_item_id}"
        ),
        claim_class=ClaimClass.PREDICTIVE,
        snapshot_id=manifest.snapshot_id,
        cohort=_cohort(manifest),
        unit=EvidenceUnit.PURCHASE_EVENT,
        support=alternative.support + alternative.comparison_support,
        mechanics_refs=alternative.mechanics_refs,
        language_ceiling=frozenset({"estimated", "conditional", "expected"}),
        estimate=alternative.dr_estimate,
        interval=alternative.comparative_interval,
        comparison_baseline=0.0,
    )


def _core_alternative_cards(
    guide: PurchaseGuide,
    manifest: SnapshotManifest,
) -> tuple[tuple[CoreAlternativeCard, ...], tuple[EvidenceClaim, ...]]:
    claims = tuple(
        _core_alternative_claim(guide, alternative, manifest)
        for alternative in guide.core_alternatives
    )
    cards = tuple(
        CoreAlternativeCard(
            item_id=alternative.item_id,
            comparator_item_id=alternative.comparator_item_id,
            stage=alternative.stage,
            trigger=alternative.trigger,
            execution=alternative.execution,
            failure_condition=alternative.failure_condition,
            mechanics_refs=alternative.mechanics_refs,
            evidence_ref=claim.claim_id,
            support=alternative.support + alternative.comparison_support,
            effective_support=alternative.effective_support,
            overlap=alternative.overlap,
            interval=alternative.comparative_interval,
            fold_estimates=alternative.fold_estimates,
        )
        for alternative, claim in zip(guide.core_alternatives, claims, strict=True)
    )
    return cards, claims


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


def _policy_evidence(
    guide: PurchaseGuide,
    definitions: dict[int, AbilityDefinition],
    manifest: SnapshotManifest,
) -> tuple[dict[str, EvidenceClaim], EvidenceClaim]:
    item_claims = {
        item.item_id: _item_claim(item, manifest=manifest)
        for item in (
            *(item for tier_items in guide.tiers.values() for item in tier_items),
            *guide.optional_core_items,
        )
    }
    evidence = {claim.claim_id: claim for claim in item_claims.values()}
    core_claim = _core_claim(guide, manifest)
    evidence[core_claim.claim_id] = core_claim
    for ability_id in definitions:
        claim = _mechanical_claim(
            claim_id=f"ability/{ability_id}/mechanics",
            mechanics_ref=f"ability/{ability_id}",
            manifest=manifest,
        )
        evidence[claim.claim_id] = claim
    return evidence, core_claim


def _core_policy_nodes(
    guide: PurchaseGuide,
    evidence_ref: str,
) -> tuple[PolicyNode, ...]:
    core_item_count = len(guide.core_items)
    return tuple(
        PolicyNode(
            f"core-{position}",
            NodeKind.PURCHASE,
            next_id=(f"core-{position + 1}" if position < core_item_count else "end"),
            evidence_ref=evidence_ref,
            item_id=item.item_id,
        )
        for position, item in enumerate(guide.core_items, start=1)
    )


@dataclass(frozen=True)
class _SituationalPolicyContext:
    hero_id: int
    hero_name: str
    core_item_ids: set[int]
    assets_by_id: dict[int, dict[str, Any]]
    hero_names: dict[int, str]
    manifest: SnapshotManifest


type _SituationalPolicyEntry = tuple[Branch, PolicyNode, CounterCard, EvidenceClaim]


def _situational_policy_entry(
    position: int,
    branch: SituationalBranch,
    context: _SituationalPolicyContext,
) -> _SituationalPolicyEntry:
    if branch.item_id in context.core_item_ids:
        raise GuideError(
            f"{context.hero_name} situational item {branch.item_id} repeats CORE"
        )
    if (
        branch.item_id not in context.assets_by_id
        or branch.comparator_item_id not in context.assets_by_id
    ):
        raise GuideError(
            f"{context.hero_name} situational branch references missing assets"
        )
    response = branch.mechanic_ref.rsplit("/", 1)[-1]
    if (
        response
        not in classify_item_threat_responses(context.assets_by_id[branch.item_id])
        or MECHANIC_RESPONSE_THREATS.get(response) != branch.threat
    ):
        raise GuideError(
            f"{context.hero_name} situational item {branch.item_id} lacks its "
            "claimed response mechanic"
        )
    claim = _situational_claim(
        branch,
        hero_id=context.hero_id,
        manifest=context.manifest,
    )
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
        assets_by_id=context.assets_by_id,
        hero_names=context.hero_names,
    )
    policy_branch = Branch(
        purchase_id,
        guards[0],
        additional_guards=tuple(guards[1:]),
    )
    purchase = PolicyNode(
        purchase_id,
        NodeKind.PURCHASE,
        next_id="end",
        evidence_ref=claim.claim_id,
        item_id=branch.item_id,
        optional=True,
        annotation=annotation,
    )
    counter_card = CounterCard(
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
    return policy_branch, purchase, counter_card, claim


@dataclass(frozen=True)
class _SituationalPolicyProjection:
    source_branches: tuple[SituationalBranch, ...]
    branches: tuple[Branch, ...]
    purchases: tuple[PolicyNode, ...]
    counter_cards: tuple[CounterCard, ...]
    claims: tuple[EvidenceClaim, ...]


def _project_situational_policy(
    inputs: _HeroInputs,
    assets_by_id: dict[int, dict[str, Any]],
    hero_names: dict[int, str],
    manifest: SnapshotManifest,
) -> _SituationalPolicyProjection:
    source_branches = (
        inputs.situational_policy.branches
        if inputs.situational_policy is not None
        else ()
    )
    context = _SituationalPolicyContext(
        inputs.analytic_guide.hero_id,
        inputs.analytic_guide.hero_name,
        {item.item_id for item in inputs.analytic_guide.core_items},
        assets_by_id,
        hero_names,
        manifest,
    )
    entries = tuple(
        _situational_policy_entry(position, branch, context)
        for position, branch in enumerate(source_branches, start=1)
    )
    return _SituationalPolicyProjection(
        source_branches,
        tuple(entry[0] for entry in entries),
        tuple(entry[1] for entry in entries),
        tuple(entry[2] for entry in entries),
        tuple(entry[3] for entry in entries),
    )


def _runtime_purchase_graph(
    core_nodes: tuple[PolicyNode, ...],
    situational: _SituationalPolicyProjection,
) -> tuple[str, tuple[PolicyNode, ...]]:
    core_position_by_item = {
        node.item_id: position for position, node in enumerate(core_nodes, start=1)
    }
    grouped: dict[int, list[tuple[Branch, PolicyNode]]] = {}
    for source, branch, purchase in zip(
        situational.source_branches,
        situational.branches,
        situational.purchases,
        strict=True,
    ):
        position = core_position_by_item.get(source.comparator_item_id)
        if position is None:
            raise GuideError(
                "situational comparator is absent from the authoritative core path"
            )
        grouped.setdefault(position, []).append((branch, purchase))

    entry_by_position = {
        position: (
            f"situational-choice-{position}"
            if position in grouped
            else f"core-{position}"
        )
        for position in range(1, len(core_nodes) + 1)
    }
    nodes: list[PolicyNode] = []
    for position, core in enumerate(core_nodes, start=1):
        successor = entry_by_position.get(position + 1, "end")
        if position in grouped:
            entries = grouped[position]
            nodes.append(
                PolicyNode(
                    f"situational-choice-{position}",
                    NodeKind.CHOICE,
                    branches=(
                        *(branch for branch, _ in entries),
                        Branch(core.node_id),
                    ),
                )
            )
        nodes.append(replace(core, next_id=successor))
        nodes.extend(
            replace(purchase, next_id=successor)
            for _, purchase in grouped.get(position, ())
        )
    return entry_by_position[1], tuple(nodes)


def _ability_policy_nodes(inputs: _HeroInputs) -> tuple[PolicyNode, ...]:
    path = inputs.analytic_guide.ability_path
    if path is None:
        raise GuideError(
            f"{inputs.analytic_guide.hero_name} has no ability prefix policy"
        )
    return tuple(
        PolicyNode(
            f"ability-{position}",
            NodeKind.ABILITY,
            evidence_ref=f"ability/{ability_id}/mechanics",
            ability_id=ability_id,
            level=scheduled.level,
        )
        for position, (ability_id, scheduled) in enumerate(
            zip(path.ability_ids, inputs.ability_timeline, strict=True),
            start=1,
        )
    )


def _policy_abstentions(
    inputs: _HeroInputs,
    *,
    has_situational_branches: bool,
) -> tuple[Abstention, ...]:
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
    if has_situational_branches:
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
    path = inputs.analytic_guide.ability_path
    minimum_ability_support = min(path.decision_support, default=0) if path else 0
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
    return tuple(abstentions)


def _build_policy(
    inputs: _HeroInputs,
    assets: list[dict[str, Any]],
    hero_names: dict[int, str],
    manifest: SnapshotManifest,
) -> tuple[BuildPolicy, ValidationContext]:
    guide = inputs.analytic_guide
    definitions = ability_definitions_from_kit(inputs.kit)
    validation = ValidationContext(
        item_graph=ItemGraph.from_assets(assets),
        ability_definitions=definitions,
        level_info=inputs.kit.get("level_info"),
    )
    if (
        not MINIMUM_BACKBONE_ITEM_COUNT
        <= len(guide.core_items)
        <= MAXIMUM_CORE_ITEM_COUNT
    ):
        raise GuideError(f"{guide.hero_name} does not have a supported core size")
    evidence, core_claim = _policy_evidence(guide, definitions, manifest)
    purchase_nodes = _core_policy_nodes(guide, core_claim.claim_id)
    assets_by_id = {
        int(asset["id"]): asset for asset in assets if isinstance(asset.get("id"), int)
    }
    situational = _project_situational_policy(
        inputs, assets_by_id, hero_names, manifest
    )
    evidence.update((claim.claim_id, claim) for claim in situational.claims)
    core_alternatives, alternative_claims = _core_alternative_cards(guide, manifest)
    evidence.update((claim.claim_id, claim) for claim in alternative_claims)
    ability_nodes = _ability_policy_nodes(inputs)
    description = inputs.kit.get("description")
    role = "evidence-grounded default"
    if isinstance(description, dict) and isinstance(description.get("role"), str):
        role = description["role"]
    entry, runtime_nodes = _runtime_purchase_graph(purchase_nodes, situational)
    nodes = (*runtime_nodes, PolicyNode("end", NodeKind.END))
    policy = BuildPolicy(
        schema_version=3,
        hero_id=guide.hero_id,
        variant="state-aware-multi-path-v3",
        invariant_kit_id=str(inputs.kit["mechanics_sha256"]),
        strategic_role=role,
        snapshot_id=manifest.snapshot_id,
        entry=entry,
        nodes=nodes,
        evidence=tuple(sorted(evidence.values(), key=lambda claim: claim.claim_id)),
        ability_plan=ability_nodes,
        abstentions=_policy_abstentions(
            inputs,
            has_situational_branches=bool(situational.source_branches),
        ),
        counter_cards=situational.counter_cards,
        core_alternatives=core_alternatives,
        path_id=guide.path_id,
        path_label=guide.path_label,
    )
    return policy, validation


def _matchups_by_hero(
    rows: list[dict[str, Any]],
    *,
    scope: str,
) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
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
    assets: list[dict[str, Any]]
    build_evidence: BuildEvidenceCatalog
    analysis_start: int
    duration_curves: dict[int, tuple[HeroDurationStat, ...]]
    same_lane_matchups: dict[int, list[dict[str, Any]]]
    whole_team_matchups: dict[int, list[dict[str, Any]]]


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


def _prepare_hero_inputs(
    api: DeadlockApi,
    hero: dict[str, Any],
    evidence: _GenerationEvidence,
) -> tuple[_HeroInputs, ...] | str:
    hero_id = int(hero["id"])
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
        ability_path = _ability_path_for_build(
            api,
            hero_id=hero_id,
            analysis_start=evidence.analysis_start,
            selected_build=selected_build,
            global_path=global_ability_path,
            use_item_filter=len(hero_builds) > 1,
        )
        analytic_guide = build_purchase_guide_from_evidence(
            hero, selected_build, ability_path=ability_path
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
    selected: list[dict[str, Any]],
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
            hero_id = int(hero["id"])
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


@dataclass(frozen=True)
class _ProjectionEnvironment:
    assets: list[dict[str, Any]]
    hero_names: dict[int, str]
    manifest: SnapshotManifest
    rank_identity: str
    build_tag_catalog: BuildTagCatalog
    duration_distribution: dict[str, Any]
    narrative_catalog: NarrativeCatalog | None
    patch: Patch


def _project_hero_guide(
    inputs: _HeroInputs,
    environment: _ProjectionEnvironment,
) -> tuple[PurchaseGuide, BuildPolicy, dict[str, Any]]:
    policy, validation = _build_policy(
        inputs,
        environment.assets,
        environment.hero_names,
        environment.manifest,
    )
    identity = ProjectionIdentity(
        hero_name=inputs.analytic_guide.hero_name,
        hero_class_name=inputs.analytic_guide.hero_class_name,
        client_version=environment.manifest.client_version,
        match_mode=environment.manifest.match_mode.value,
        rank_identity=environment.rank_identity,
    )
    projected = project_policy_to_guide(
        policy,
        validation,
        assets=environment.assets,
        identity=identity,
        layout_source=inputs.analytic_guide,
    )
    projected = replace(projected, ability_path=inputs.analytic_guide.ability_path)
    try:
        tag_selection = select_build_tags(
            tuple(item.item_id for item in projected.core_items),
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
        rank_identity=environment.rank_identity,
        analysis_start_timestamp=environment.manifest.epochs.analysis_start_timestamp,
        as_of_timestamp=environment.manifest.as_of_timestamp,
    )
    context = build_hero_strategy_context(
        analytic,
        inputs.hero,
        environment.assets,
        inputs.duration_curve,
        environment.duration_distribution,
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
) -> tuple[list[PurchaseGuide], list[BuildPolicy], list[dict[str, Any]]]:
    guides: list[PurchaseGuide] = []
    policies: list[BuildPolicy] = []
    contexts: list[dict[str, Any]] = []
    for inputs in inputs_by_hero:
        guide, policy, context = _project_hero_guide(inputs, environment)
        guides.append(guide)
        policies.append(policy)
        contexts.append(context)
    return guides, policies, contexts


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
    hero_names = {
        int(hero["id"]): str(hero.get("name") or hero["id"]) for hero in heroes
    }
    projection_environment = _ProjectionEnvironment(
        assets,
        hero_names,
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
                for item_id in context["item_mechanics_ids"]
            },
        ),
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
