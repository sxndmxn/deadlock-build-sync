from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from .ability_order import LOW_ABILITY_DECISION_SUPPORT
from .build_evidence import (
    MAXIMUM_CORE_ITEM_COUNT,
    MECHANIC_RESPONSE_THREATS,
    MINIMUM_BACKBONE_ITEM_COUNT,
)
from .mechanics import (
    ItemGraph,
    ability_definitions_from_kit,
    classify_item_threat_responses,
)
from .policy import (
    Abstention,
    AbstentionReason,
    Branch,
    BuildPolicy,
    CounterCard,
    EvidenceClaim,
    Guard,
    GuardOperator,
    NodeKind,
    PolicyNode,
    ValidationContext,
)
from .power_curve import (
    summarize_ending_duration_profile,
)
from .value_validation import integer, object_dict

if TYPE_CHECKING:
    from .build_evidence import (
        SituationalBranch,
    )
    from .purchase_guide import PurchaseGuide
    from .snapshot import SnapshotManifest

from .service_claims import (
    _core_alternative_cards,
    _policy_evidence,
    _situational_annotation,
    _situational_claim,
)
from .service_types import GuideError, _HeroInputs


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
    assets_by_id: dict[int, dict[str, object]]
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
                (
                    "enemy.lane_heroes"
                    if branch.enemy_scope == "same_lane"
                    else "enemy.heroes"
                ),
                GuardOperator.CONTAINS,
                branch.enemy_hero_id,
            )
        )
    phase_bounds = {
        0: (0, 539),
        1: (540, 1_199),
        2: (1_200, 1_799),
        3: (1_800, None),
    }
    earliest_time_s, latest_time_s = phase_bounds[branch.phase]
    guards.append(Guard("clock_s", GuardOperator.AT_LEAST, earliest_time_s))
    if latest_time_s is not None:
        guards.append(Guard("clock_s", GuardOperator.AT_MOST, latest_time_s))
    annotation = _situational_annotation(
        branch,
        assets_by_id=context.assets_by_id,
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
        enemy_scope=branch.enemy_scope,
        phase=branch.phase,
        tier=branch.tier,
        enemy_mechanics_refs=branch.enemy_mechanics_refs,
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
    assets_by_id: dict[int, dict[str, object]],
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
    assets: list[dict[str, object]],
    manifest: SnapshotManifest,
) -> tuple[BuildPolicy, ValidationContext]:
    guide = inputs.analytic_guide
    definitions = ability_definitions_from_kit(inputs.kit)
    validation = ValidationContext(
        item_graph=ItemGraph.from_assets(assets),
        ability_definitions=definitions,
        level_info=inputs.kit.get("level_info"),
    )
    core_item_count = len(guide.core_items)
    if (
        core_item_count < MINIMUM_BACKBONE_ITEM_COUNT
        or core_item_count > MAXIMUM_CORE_ITEM_COUNT
    ):
        raise GuideError(f"{guide.hero_name} does not have a supported core size")
    evidence, core_claim = _policy_evidence(guide, definitions, manifest)
    purchase_nodes = _core_policy_nodes(guide, core_claim.claim_id)
    assets_by_id = {
        integer(asset["id"]): asset
        for asset in assets
        if isinstance(asset.get("id"), int)
    }
    situational = _project_situational_policy(inputs, assets_by_id, manifest)
    evidence.update((claim.claim_id, claim) for claim in situational.claims)
    core_alternatives, alternative_claims = _core_alternative_cards(guide, manifest)
    evidence.update((claim.claim_id, claim) for claim in alternative_claims)
    ability_nodes = _ability_policy_nodes(inputs)
    description = object_dict(inputs.kit.get("description"))
    role = "evidence-grounded default"
    if description is not None and isinstance(description.get("role"), str):
        role = str(description["role"])
    entry, runtime_nodes = _runtime_purchase_graph(purchase_nodes, situational)
    nodes = (*runtime_nodes, PolicyNode("end", NodeKind.END))
    policy = BuildPolicy(
        schema_version=5,
        hero_id=guide.hero_id,
        variant="state-aware-multi-path-v5",
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
