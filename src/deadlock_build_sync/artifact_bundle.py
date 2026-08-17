from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, cast

from .ability_order import AbilityPath
from .api import Patch
from .artifacts import ArtifactError, validate_policy_artifact
from .build_evidence import (
    BuildEvidenceCatalog,
    HeroBuildEvidence,
    evidence_record_sha256,
    load_build_evidence,
)
from .build_tags import AXIS_CLASSES, COMPLEXITY_CLASS, FUNCTION_CLASSES
from .narratives import apply_narrative, load_narrative_catalog
from .policy import BuildPolicy, NodeKind
from .purchase_guide import (
    GuideCategory,
    GuideItem,
    PurchaseGuide,
    guide_item_from_evidence,
)
from .ranks import Rank, RankDivision, RankRange, RankTier
from .snapshot import sha256_json
from .strategy_context import validate_strategy_context_document

if TYPE_CHECKING:
    from pathlib import Path

    from .narratives import NarrativeCatalog


class ArtifactBundleError(ValueError):
    """Raised when reviewed install artifacts do not form one exact bundle."""


_COVERAGE_MISMATCH = "artifact bundle coverage differs across files"

type _PatchDocument = dict[str, Any]
type _RankBoundary = dict[str, Any]
type _PolicyDocumentRow = dict[str, Any]
type _HeroContextRow = dict[str, Any]


@dataclass(frozen=True)
class ArtifactGuideBundle:
    guides: list[PurchaseGuide]
    snapshot_manifest: dict[str, Any]
    patch: Patch
    rank_range: RankRange
    expected_hero_ids: frozenset[int]
    exclusions: tuple[tuple[int, str], ...]


@dataclass(frozen=True)
class ArtifactBuildIdentity:
    tag_ids: tuple[int, ...]
    tag_classes: tuple[str, ...]
    tag_labels: tuple[str, ...]
    catalog_sha256: str
    archetype: str


def _read_document(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ArtifactBundleError(f"could not read {label} {path}: {error}") from error
    if not isinstance(value, dict):
        raise ArtifactBundleError(f"{label} root must be an object: {path}")
    return value


def _snapshot_identity(manifest: dict[str, Any]) -> str:
    payload = dict(manifest)
    payload.pop("snapshot_id", None)
    payload.pop("created_at", None)
    records = payload.get("records")
    if not isinstance(records, list) or not records:
        raise ArtifactBundleError("artifact snapshot has no source records")
    stable_records: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            raise ArtifactBundleError("artifact snapshot contains a malformed record")
        stable = dict(record)
        stable.pop("fetched_at", None)
        stable_records.append(stable)
    payload["records"] = stable_records
    return sha256_json(payload)


def _patch(value: object) -> Patch:
    if not isinstance(value, dict):
        raise ArtifactBundleError("artifact bundle has no patch identity")
    data = cast("_PatchDocument", value)
    try:
        patch = Patch(
            title=str(data["title"]),
            start_timestamp=int(data["start_timestamp"]),
            published_at=str(data["published_at"]),
            source=str(data["source"]),
            guid=str(data["guid"]),
            link=str(data["link"]),
            content_sha256=str(data["content_sha256"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ArtifactBundleError(
            f"artifact bundle has a malformed patch: {error}"
        ) from error
    if data.get("identity") != patch.identity:
        raise ArtifactBundleError(
            "artifact patch fingerprint does not match its contents"
        )
    return patch


def _rank_from_boundary(value: object, label: str) -> Rank:
    if not isinstance(value, dict) or not isinstance(value.get("badge_id"), int):
        raise ArtifactBundleError(f"artifact bundle has no numeric {label} rank")
    data = cast("_RankBoundary", value)
    badge_id = cast("int", data["badge_id"])
    tier, division = divmod(badge_id, 10)
    try:
        rank = Rank(RankTier(tier), RankDivision(division))
    except ValueError as error:
        raise ArtifactBundleError(
            f"artifact bundle has an invalid {label} rank"
        ) from error
    if badge_id != rank.badge_id:
        raise ArtifactBundleError(f"artifact bundle has an invalid {label} badge")
    return rank


def _rank_range(value: object) -> RankRange:
    if not isinstance(value, dict):
        raise ArtifactBundleError("artifact bundle has no rank range")
    return RankRange(
        _rank_from_boundary(value.get("minimum"), "minimum"),
        _rank_from_boundary(value.get("maximum"), "maximum"),
    )


def _policy_core(policy: BuildPolicy) -> tuple[int, ...]:
    nodes = {node.node_id: node for node in policy.nodes}
    current = policy.entry
    visited: set[str] = set()
    item_ids: list[int] = []
    while current not in visited:
        visited.add(current)
        node = nodes.get(current)
        if node is None:
            raise ArtifactBundleError(
                f"hero {policy.hero_id} policy has a dangling default path"
            )
        if node.kind == NodeKind.END:
            break
        if node.kind != NodeKind.PURCHASE or node.item_id is None:
            raise ArtifactBundleError(
                f"hero {policy.hero_id} artifact core is not a purchase-only path"
            )
        item_ids.append(node.item_id)
        if node.next_id is None:
            raise ArtifactBundleError(
                f"hero {policy.hero_id} policy core ends without an end node"
            )
        current = node.next_id
    else:
        raise ArtifactBundleError(f"hero {policy.hero_id} policy core contains a cycle")
    if len(item_ids) != 8:
        raise ArtifactBundleError(
            f"hero {policy.hero_id} artifact core must contain exactly eight items"
        )
    return tuple(item_ids)


def _optional_int(value: object, label: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or value < 0:
        raise ArtifactBundleError(f"artifact projection has an invalid {label}")
    return value


def _guide_item(
    value: object,
    *,
    evidence: HeroBuildEvidence,
    expected_tier: int | None,
) -> GuideItem:
    if not isinstance(value, dict):
        raise ArtifactBundleError("artifact projection contains a malformed item")
    item_id = value.get("item_id")
    name = value.get("item")
    if not isinstance(item_id, int) or item_id <= 0:
        raise ArtifactBundleError("artifact projection contains an incomplete item")
    if not isinstance(name, str) or not name.strip():
        raise ArtifactBundleError("artifact projection contains an incomplete item")
    item_evidence = next(
        (item for item in evidence.items if item.item_id == item_id),
        None,
    )
    if item_evidence is None or item_evidence.item != name.strip():
        raise ArtifactBundleError(
            f"hero {evidence.hero_id} projection item {item_id} conflicts with build evidence"
        )
    if expected_tier is not None and item_evidence.tier != expected_tier:
        raise ArtifactBundleError(
            f"hero {evidence.hero_id} projection item {item_id} has the wrong tier"
        )
    return replace(
        guide_item_from_evidence(item_evidence),
        required_flex_slots=_optional_int(
            value.get("required_flex_slots"), "flex-slot requirement"
        ),
        sell_priority=_optional_int(value.get("sell_priority"), "sell priority"),
        imbue_target_ability_id=_optional_int(
            value.get("imbue_target_ability_id"), "imbue target"
        ),
    )


type _CategorySpec = tuple[str, bool, int, int]


def _projection_category_rows(
    hero: dict[str, Any],
    expected: tuple[_CategorySpec, ...],
    hero_id: int,
) -> list[object]:
    projection = hero.get("projection")
    rows = projection.get("categories") if isinstance(projection, dict) else None
    if not isinstance(rows, list) or len(rows) != len(expected):
        raise ArtifactBundleError(
            f"hero {hero_id} artifact projection must contain five rows"
        )
    return rows


def _projected_category(
    raw: object,
    spec: _CategorySpec,
    *,
    index: int,
    evidence: HeroBuildEvidence,
) -> tuple[GuideCategory, tuple[GuideItem, ...]]:
    name, optional, minimum, maximum = spec
    raw_items = raw.get("items") if isinstance(raw, dict) else None
    if (
        not isinstance(raw, dict)
        or raw.get("name") != name
        or raw.get("optional") is not optional
        or not isinstance(raw_items, list)
        or not minimum <= len(raw_items) <= maximum
    ):
        raise ArtifactBundleError(
            f"hero {evidence.hero_id} artifact row {name} is malformed"
        )
    items = tuple(
        _guide_item(item, evidence=evidence, expected_tier=index or None)
        for item in raw_items
    )
    if index != 0 and len({item.item_id for item in items}) != len(items):
        raise ArtifactBundleError(
            f"hero {evidence.hero_id} artifact row {name} contains duplicates"
        )
    return GuideCategory(name, items, optional=optional), items


def _final_core_items(
    items: tuple[GuideItem, ...],
    core_path_ids: tuple[int, ...],
    policy_core_ids: tuple[int, ...],
    hero_id: int,
) -> tuple[GuideItem, ...]:
    if tuple(item.item_id for item in items) != core_path_ids:
        raise ArtifactBundleError(
            f"hero {hero_id} projection CORE path differs from component-expanded evidence"
        )
    by_id = {item.item_id: item for item in items}
    if not set(policy_core_ids) <= set(by_id):
        raise ArtifactBundleError(
            f"hero {hero_id} projection CORE path omits final items"
        )
    return tuple(by_id[item_id] for item_id in policy_core_ids)


def _validate_projected_item_sets(
    core_items: tuple[GuideItem, ...],
    tiers: dict[int, tuple[GuideItem, ...]],
    policy_core_ids: tuple[int, ...],
    hero_id: int,
) -> None:
    if tuple(item.item_id for item in core_items) != policy_core_ids:
        raise ArtifactBundleError(
            f"hero {hero_id} projection core differs from its policy"
        )
    core_ids = {item.item_id for item in core_items}
    tier_ids = {item.item_id for tier_items in tiers.values() for item in tier_items}
    if core_ids & tier_ids:
        raise ArtifactBundleError(f"hero {hero_id} optional rows repeat CORE items")


def _categories(
    hero: dict[str, Any],
    policy: BuildPolicy,
    evidence: HeroBuildEvidence,
) -> tuple[
    tuple[GuideCategory, ...], tuple[GuideItem, ...], dict[int, tuple[GuideItem, ...]]
]:
    policy_core_ids = _policy_core(policy)
    core_path_ids = (
        evidence.sequence_policy.default_path
        if evidence.sequence_policy is not None
        else policy_core_ids
    )
    expected: tuple[_CategorySpec, ...] = (
        ("CORE ITEMS", False, len(core_path_ids), len(core_path_ids)),
        ("TIER 1", True, 1, 10),
        ("TIER 2", True, 1, 10),
        ("TIER 3", True, 1, 10),
        ("TIER 4", True, 1, 10),
    )
    raw_categories = _projection_category_rows(hero, expected, policy.hero_id)
    categories: list[GuideCategory] = []
    tiers: dict[int, tuple[GuideItem, ...]] = {}
    core_items: tuple[GuideItem, ...] = ()
    for index, (raw, spec) in enumerate(zip(raw_categories, expected, strict=True)):
        category, items = _projected_category(
            raw,
            spec,
            index=index,
            evidence=evidence,
        )
        categories.append(category)
        if index == 0:
            core_items = _final_core_items(
                items, core_path_ids, policy_core_ids, policy.hero_id
            )
        else:
            tiers[index] = items
    _validate_projected_item_sets(core_items, tiers, policy_core_ids, policy.hero_id)
    return tuple(categories), core_items, tiers


def _ability_projection(
    raw: dict[str, Any], policy: BuildPolicy
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    steps = raw["steps"]
    if len(steps) != 16:
        raise ArtifactBundleError(
            f"hero {policy.hero_id} ability policy must contain 16 actions"
        )
    ability_ids: list[int] = []
    decision_support: list[int] = []
    for step in steps:
        if (
            not isinstance(step, dict)
            or not isinstance(step.get("ability_id"), int)
            or not isinstance(step.get("decision_reached_support"), int)
            or int(step["decision_reached_support"]) <= 0
        ):
            raise ArtifactBundleError(
                f"hero {policy.hero_id} has a malformed ability action"
            )
        ability_ids.append(int(step["ability_id"]))
        decision_support.append(int(step["decision_reached_support"]))
    if len(Counter(ability_ids)) != 4 or any(
        count != 4 for count in Counter(ability_ids).values()
    ):
        raise ArtifactBundleError(
            f"hero {policy.hero_id} ability policy is not a complete four-rank path"
        )
    policy_abilities = tuple(
        node.ability_id
        for node in policy.ability_plan
        if node.kind == NodeKind.ABILITY and node.ability_id is not None
    )
    if tuple(ability_ids) != policy_abilities:
        raise ArtifactBundleError(
            f"hero {policy.hero_id} ability projection differs from its policy"
        )
    return tuple(ability_ids), tuple(decision_support)


def _ability_path(hero: dict[str, Any], policy: BuildPolicy) -> AbilityPath:
    raw = hero.get("ability_policy")
    if not isinstance(raw, dict) or not isinstance(raw.get("steps"), list):
        raise ArtifactBundleError(f"hero {policy.hero_id} has no ability policy")
    ability_ids, decision_support = _ability_projection(raw, policy)
    integer_fields = (
        "all_valid_telemetry_appearances",
        "complete_path_appearances",
        "final_branch_support",
    )
    if any(not isinstance(raw.get(field), int) for field in integer_fields):
        raise ArtifactBundleError(
            f"hero {policy.hero_id} ability policy has invalid support"
        )
    cohort_matches = int(raw["all_valid_telemetry_appearances"])
    complete_matches = int(raw["complete_path_appearances"])
    matches = int(raw["final_branch_support"])
    rate = raw.get("observed_final_branch_outcome_rate")
    if cohort_matches <= 0 or complete_matches <= 0 or matches <= 0:
        raise ArtifactBundleError(
            f"hero {policy.hero_id} ability policy has incoherent support"
        )
    if matches > complete_matches or complete_matches > cohort_matches:
        raise ArtifactBundleError(
            f"hero {policy.hero_id} ability policy has incoherent support"
        )
    if not isinstance(rate, (int, float)) or not 0.0 <= float(rate) <= 1.0:
        raise ArtifactBundleError(
            f"hero {policy.hero_id} ability policy has incoherent support"
        )
    wins = round(float(rate) * matches)
    return AbilityPath(
        ability_ids=ability_ids,
        matches=matches,
        wins=wins,
        losses=matches - wins,
        cohort_matches=cohort_matches,
        complete_path_matches=complete_matches,
        decision_support=decision_support,
        selection=str(raw.get("selection") or "MOST_SUPPORTED_LEGAL_STATE"),
    )


def _hero_identity(hero: dict[str, Any], policy: BuildPolicy) -> tuple[str, str]:
    hero_id = hero.get("hero_id")
    hero_name = hero.get("hero")
    mechanics = hero.get("hero_mechanics")
    if hero_id != policy.hero_id or not isinstance(hero_name, str):
        raise ArtifactBundleError(f"hero {policy.hero_id} has inconsistent identity")
    if not hero_name.strip() or not isinstance(mechanics, dict):
        raise ArtifactBundleError(f"hero {policy.hero_id} has inconsistent identity")
    class_name = mechanics.get("class_name")
    if not isinstance(class_name, str) or not class_name.strip():
        raise ArtifactBundleError(f"hero {policy.hero_id} has inconsistent identity")
    if (
        hero.get("policy_id") != policy.policy_id
        or hero.get("snapshot_id") != policy.snapshot_id
    ):
        raise ArtifactBundleError(f"hero {policy.hero_id} has inconsistent identity")
    return hero_name.strip(), class_name.strip()


def _core_evidence(
    hero: dict[str, Any], policy: BuildPolicy
) -> tuple[int, float, int, int]:
    core = hero.get("core")
    if not isinstance(core, dict):
        raise ArtifactBundleError(f"hero {policy.hero_id} has no core evidence")
    joint_matches = core.get("joint_player_matches")
    joint_share = core.get("joint_share")
    median_net_worth = core.get("median_final_net_worth")
    target_cost = core.get("core_target_cost")
    if not isinstance(joint_matches, int) or joint_matches <= 0:
        raise ArtifactBundleError(f"hero {policy.hero_id} has invalid core evidence")
    if not isinstance(joint_share, (int, float)) or not 0.0 < float(joint_share) <= 1.0:
        raise ArtifactBundleError(f"hero {policy.hero_id} has invalid core evidence")
    if not isinstance(median_net_worth, int) or median_net_worth <= 0:
        raise ArtifactBundleError(f"hero {policy.hero_id} has invalid core evidence")
    if (
        not isinstance(target_cost, int)
        or target_cost <= 0
        or target_cost > median_net_worth
    ):
        raise ArtifactBundleError(f"hero {policy.hero_id} has invalid core evidence")
    return joint_matches, float(joint_share), median_net_worth, target_cost


def _valid_tag_list(values: object, *, integers: bool) -> bool:
    if not isinstance(values, list) or len(values) != 3:
        return False
    if integers:
        return (
            all(
                isinstance(value, int) and not isinstance(value, bool) and value > 0
                for value in values
            )
            and len(set(values)) == 3
        )
    return all(isinstance(value, str) and bool(value) for value in values)


def _build_identity(
    hero: dict[str, Any],
    policy: BuildPolicy,
    manifest: dict[str, Any],
) -> ArtifactBuildIdentity:
    projection = hero.get("projection")
    build = projection.get("build") if isinstance(projection, dict) else None
    if not isinstance(build, dict):
        raise ArtifactBundleError(f"hero {policy.hero_id} has no build identity")
    tag_ids = build.get("tag_ids")
    classes = build.get("tag_classes")
    labels = build.get("tag_labels")
    catalog_sha256 = build.get("tag_catalog_sha256")
    archetype = build.get("archetype")
    if (
        not _valid_tag_list(tag_ids, integers=True)
        or not _valid_tag_list(classes, integers=False)
        or not _valid_tag_list(labels, integers=False)
    ):
        raise ArtifactBundleError(f"hero {policy.hero_id} has invalid build tags")
    if (
        not isinstance(catalog_sha256, str)
        or catalog_sha256 != manifest.get("build_tags_sha256")
        or not isinstance(archetype, str)
        or not archetype.strip()
    ):
        raise ArtifactBundleError(f"hero {policy.hero_id} has invalid build tags")
    resolved_ids = cast("list[int]", tag_ids)
    resolved_classes = cast("list[str]", classes)
    resolved_labels = cast("list[str]", labels)
    resolved_catalog = cast("str", catalog_sha256)
    resolved_archetype = cast("str", archetype)
    if (
        resolved_classes[0] not in AXIS_CLASSES
        or resolved_classes[1] not in FUNCTION_CLASSES
        or resolved_classes[2] != COMPLEXITY_CLASS
    ):
        raise ArtifactBundleError(f"hero {policy.hero_id} has invalid build tags")
    return ArtifactBuildIdentity(
        tuple(resolved_ids),
        tuple(resolved_classes),
        tuple(resolved_labels),
        resolved_catalog,
        resolved_archetype.strip(),
    )


def _guide(
    hero: dict[str, Any],
    policy: BuildPolicy,
    evidence: HeroBuildEvidence,
    *,
    manifest: dict[str, Any],
    rank_identity: str,
) -> PurchaseGuide:
    hero_name, class_name = _hero_identity(hero, policy)
    categories, core_items, tiers = _categories(hero, policy, evidence)
    joint_matches, joint_share, median_net_worth, target_cost = _core_evidence(
        hero, policy
    )
    build_identity = _build_identity(
        hero,
        policy,
        manifest,
    )
    client_version = manifest.get("client_version")
    match_mode = manifest.get("match_mode")
    as_of_timestamp = manifest.get("as_of_timestamp")
    if (
        not isinstance(client_version, int)
        or not isinstance(match_mode, str)
        or not isinstance(as_of_timestamp, int)
    ):
        raise ArtifactBundleError("artifact snapshot has an invalid cohort")
    return PurchaseGuide(
        hero_id=policy.hero_id,
        hero_name=hero_name,
        hero_class_name=class_name,
        tiers=tiers,
        ability_path=_ability_path(hero, policy),
        categories=categories,
        snapshot_id=policy.snapshot_id,
        policy_id=policy.policy_id,
        client_version=client_version,
        match_mode=match_mode,
        rank_identity=rank_identity,
        core_items=core_items,
        core_purchase_items=categories[0].items,
        core_joint_matches=joint_matches,
        core_joint_share=joint_share,
        median_final_net_worth=median_net_worth,
        core_target_cost=target_cost,
        build_tag_ids=build_identity.tag_ids,
        build_tag_classes=build_identity.tag_classes,
        build_tag_labels=build_identity.tag_labels,
        build_tag_catalog_sha256=build_identity.catalog_sha256,
        build_archetype=build_identity.archetype,
        as_of_timestamp=as_of_timestamp,
    )


def _exclusions(value: object) -> tuple[tuple[int, str], ...]:
    if not isinstance(value, list):
        raise ArtifactBundleError("artifact bundle has invalid exclusions")
    result: list[tuple[int, str]] = []
    for row in value:
        if not isinstance(row, dict):
            raise ArtifactBundleError("artifact bundle has a malformed exclusion")
        hero_id = row.get("hero_id")
        reason = row.get("reason")
        if (
            not isinstance(hero_id, int)
            or not isinstance(reason, str)
            or not reason.strip()
        ):
            raise ArtifactBundleError("artifact bundle has a malformed exclusion")
        result.append((hero_id, reason.strip()))
    return tuple(result)


def _validated_manifest(
    context: dict[str, Any],
    policies: dict[str, Any],
    catalog: NarrativeCatalog,
) -> dict[str, Any]:
    manifest = context.get("snapshot_manifest")
    if not isinstance(manifest, dict):
        raise ArtifactBundleError("strategy context has no snapshot manifest")
    data: dict[str, Any] = manifest
    if policies.get("snapshot_manifest") != data:
        raise ArtifactBundleError("context and policy snapshot manifests differ")
    snapshot_id = data.get("snapshot_id")
    if snapshot_id != _snapshot_identity(data):
        raise ArtifactBundleError(
            "artifact snapshot fingerprint does not match its sources"
        )
    if catalog.snapshot_id != snapshot_id:
        raise ArtifactBundleError("narratives use another artifact snapshot")
    if catalog.source_context_sha256 != context.get("source_context_sha256"):
        raise ArtifactBundleError("narratives use another strategy context")
    return data


def _validated_coverage(
    context: dict[str, Any],
    policies: dict[str, Any],
    catalog: NarrativeCatalog,
) -> tuple[tuple[int, str], ...]:
    requested = context.get("requested_hero_ids")
    exclusions = _exclusions(context.get("exclusions"))
    if not isinstance(requested, list) or not all(
        isinstance(hero_id, int) for hero_id in requested
    ):
        raise ArtifactBundleError("artifact bundle has invalid requested heroes")
    if requested != policies.get("requested_hero_ids"):
        raise ArtifactBundleError(_COVERAGE_MISMATCH)
    if context.get("exclusions") != policies.get("exclusions"):
        raise ArtifactBundleError(_COVERAGE_MISMATCH)
    if catalog.requested_hero_ids != frozenset(requested):
        raise ArtifactBundleError(_COVERAGE_MISMATCH)
    if catalog.exclusions != dict(exclusions):
        raise ArtifactBundleError(_COVERAGE_MISMATCH)
    return exclusions


def _validated_cohort(
    context: dict[str, Any],
    manifest: dict[str, Any],
    catalog: NarrativeCatalog,
) -> tuple[Patch, RankRange, str]:
    patch = _patch(context.get("patch"))
    if manifest.get("patch") != context.get("patch"):
        raise ArtifactBundleError("artifact patch differs from its snapshot manifest")
    if catalog.patch_identity != patch.identity:
        raise ArtifactBundleError("narratives use another patch")
    if manifest.get("game_mode") != "normal" or catalog.game_mode != "normal":
        raise ArtifactBundleError("artifact bundle is not for the normal ruleset")
    if catalog.client_version != manifest.get("client_version"):
        raise ArtifactBundleError("narrative cohort differs from the artifact snapshot")
    if catalog.match_mode != manifest.get("match_mode"):
        raise ArtifactBundleError("narrative cohort differs from the artifact snapshot")
    rank_data = manifest.get("rank_range")
    rank_range = _rank_range(rank_data)
    if not isinstance(rank_data, dict) or not isinstance(rank_data.get("label"), str):
        raise ArtifactBundleError("artifact bundle has no rank label")
    if rank_data.get("labels_sha256") != manifest.get("rank_labels_sha256"):
        raise ArtifactBundleError("artifact rank labels differ from its snapshot")
    return patch, rank_range, str(rank_data["label"])


def _decoded_policies(document: dict[str, Any]) -> dict[int, BuildPolicy]:
    rows = cast("list[object]", document["policies"])
    decoded = [
        BuildPolicy.from_dict(cast("_PolicyDocumentRow", row))
        for row in rows
        if isinstance(row, dict)
    ]
    return {policy.hero_id: policy for policy in decoded}


def _hero_contexts(document: dict[str, Any]) -> dict[int, dict[str, Any]]:
    rows = cast("list[object]", document["heroes"])
    heroes: dict[int, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        hero = cast("_HeroContextRow", row)
        hero_id = hero.get("hero_id")
        if isinstance(hero_id, int):
            heroes[hero_id] = hero
    return heroes


def _evidence_snapshot_record(
    manifest: dict[str, Any],
    catalog: BuildEvidenceCatalog,
) -> dict[str, Any]:
    records = manifest.get("records")
    evidence_records = (
        [
            record
            for record in records
            if isinstance(record, dict)
            and record.get("path") == "artifact:build-evidence"
        ]
        if isinstance(records, list)
        else []
    )
    if len(evidence_records) != 1:
        raise ArtifactBundleError(
            "artifact snapshot must contain one build-evidence record"
        )
    record = evidence_records[0]
    parameters = record.get("parameters")
    if (
        not isinstance(parameters, dict)
        or parameters.get("artifact_id") != catalog.artifact_id
        or record.get("sha256") != evidence_record_sha256(catalog)
        or record.get("byte_count") != len(catalog.raw_bytes)
    ):
        raise ArtifactBundleError("build evidence differs from the artifact snapshot")
    return record


def _build_evidence_compatibility(
    catalog: BuildEvidenceCatalog,
    context: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, bool]:
    requested = context.get("requested_hero_ids")
    rank = manifest.get("rank_range")
    cohort = catalog.cohort
    return {
        "client version": catalog.client_version == manifest.get("client_version"),
        "patch": catalog.patch.get("identity")
        == (manifest.get("patch") or {}).get("identity"),
        "as-of cutoff": catalog.as_of_timestamp == manifest.get("as_of_timestamp"),
        "match mode": str(cohort.get("match_mode") or "").casefold()
        == str(manifest.get("match_mode") or "").casefold(),
        "game mode": str(cohort.get("game_mode") or "").casefold()
        == str(manifest.get("game_mode") or "").casefold(),
        "minimum rank": isinstance(rank, dict)
        and cohort.get("minimum_badge") == (rank.get("minimum") or {}).get("badge_id"),
        "maximum rank": isinstance(rank, dict)
        and cohort.get("maximum_badge") == (rank.get("maximum") or {}).get("badge_id"),
        "rank labels": catalog.rank_labels_sha256 == manifest.get("rank_labels_sha256"),
        "epochs": catalog.epochs.as_dict() == manifest.get("epochs"),
        "hero coverage": isinstance(requested, list)
        and catalog.requested_hero_ids == frozenset(requested),
    }


def _validated_build_evidence(
    path: Path,
    context: dict[str, Any],
    manifest: dict[str, Any],
) -> BuildEvidenceCatalog:
    try:
        catalog = load_build_evidence(path)
    except ArtifactError as error:
        raise ArtifactBundleError(str(error)) from error
    _evidence_snapshot_record(manifest, catalog)
    checks = _build_evidence_compatibility(catalog, context, manifest)
    differences = [label for label, compatible in checks.items() if not compatible]
    if differences:
        raise ArtifactBundleError(
            "build evidence is incompatible with the reviewed bundle in: "
            + ", ".join(differences)
        )
    return catalog


def load_artifact_guide_bundle(
    context_path: Path,
    policy_path: Path,
    narrative_path: Path,
    build_evidence_path: Path,
) -> ArtifactGuideBundle:
    """Load one fully reviewed guide bundle without re-fetching analytics.

    Returns:
        Installable guides whose context, policy, narrative, and projection identities
        are exact matches.

    Raises:
        ArtifactBundleError: If any artifact is malformed, edited, stale, or crossed.

    """
    context = _read_document(context_path, "strategy context")
    policies = _read_document(policy_path, "policy artifact")
    validate_strategy_context_document(context)
    validate_policy_artifact(policies)
    catalog = load_narrative_catalog(narrative_path)

    manifest = _validated_manifest(context, policies, catalog)
    exclusions = _validated_coverage(context, policies, catalog)
    patch, rank_range, rank_identity = _validated_cohort(context, manifest, catalog)
    build_evidence = _validated_build_evidence(
        build_evidence_path,
        context,
        manifest,
    )
    by_policy = _decoded_policies(policies)
    heroes = _hero_contexts(context)
    if set(heroes) != set(by_policy):
        raise ArtifactBundleError(
            "strategy contexts and policies cover different heroes"
        )

    guides = []
    for hero_id in sorted(heroes):
        hero_context = heroes[hero_id]
        guide = _guide(
            hero_context,
            by_policy[hero_id],
            build_evidence.heroes[hero_id],
            manifest=manifest,
            rank_identity=rank_identity,
        )
        guides.append(apply_narrative(guide, hero_context, patch, catalog))
    return ArtifactGuideBundle(
        guides=guides,
        snapshot_manifest=manifest,
        patch=patch,
        rank_range=rank_range,
        expected_hero_ids=frozenset(heroes),
        exclusions=exclusions,
    )
