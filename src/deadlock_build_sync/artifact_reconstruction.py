from __future__ import annotations

from typing import TYPE_CHECKING, cast

from .artifact_bundle_types import (
    ArtifactBuildIdentity,
    ArtifactBundleError,
)
from .artifact_projection import _ability_path, _categories
from .build_tags import FUNCTION_CLASSES
from .purchase_guide import (
    PurchaseGuide,
    guide_item_from_evidence,
)
from .value_validation import integer, object_dict

if TYPE_CHECKING:
    from .build_evidence import HeroBuildEvidence
    from .policy import BuildPolicy


def _hero_identity(hero: dict[str, object], policy: BuildPolicy) -> tuple[str, str]:
    hero_id = hero.get("hero_id")
    hero_name = hero.get("hero")
    mechanics = hero.get("hero_mechanics")
    if (
        hero_id != policy.hero_id
        or hero.get("path_id") != policy.path_id
        or not isinstance(hero_name, str)
    ):
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
    hero: dict[str, object], policy: BuildPolicy
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
    hero: dict[str, object],
    policy: BuildPolicy,
    manifest: dict[str, object],
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
    resolved_catalog = catalog_sha256
    resolved_archetype = archetype
    if (
        not all(value.strip() for value in resolved_classes[:2])
        or resolved_classes[2] not in FUNCTION_CLASSES
    ):
        raise ArtifactBundleError(f"hero {policy.hero_id} has invalid build tags")
    return ArtifactBuildIdentity(
        tuple(resolved_ids),
        tuple(resolved_classes),
        tuple(resolved_labels),
        resolved_catalog,
        resolved_archetype.strip(),
    )


def _analysis_start_timestamp(manifest: dict[str, object]) -> int:
    epochs = object_dict(manifest.get("epochs"))
    starts: list[int] = []
    for value in epochs.values() if epochs is not None else ():
        row = object_dict(value)
        if row is not None and isinstance(row.get("start_timestamp"), int):
            starts.append(integer(row["start_timestamp"]))
    if len(starts) != 4:
        raise ArtifactBundleError("artifact snapshot has invalid epoch boundaries")
    return max(starts)


def _guide(
    hero: dict[str, object],
    policy: BuildPolicy,
    evidence: HeroBuildEvidence,
    *,
    manifest: dict[str, object],
    rank_identity: str,
) -> PurchaseGuide:
    hero_name, class_name = _hero_identity(hero, policy)
    categories, core_items, optional_core_items, tiers = _categories(
        hero, policy, evidence
    )
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
        path_id=policy.path_id,
        path_label=policy.path_label,
        signature_item_ids=evidence.signature_item_ids,
        ability_path=_ability_path(hero, policy),
        categories=categories,
        snapshot_id=policy.snapshot_id,
        policy_id=policy.policy_id,
        client_version=client_version,
        match_mode=match_mode,
        rank_identity=rank_identity,
        core_items=core_items,
        core_purchase_items=categories[0].items,
        backbone_items=tuple(
            guide_item_from_evidence(
                next(item for item in evidence.items if item.item_id == item_id)
            )
            for item_id in evidence.core_policy.backbone_item_ids
        ),
        optional_core_items=optional_core_items,
        core_alternatives=evidence.core_policy.alternatives,
        backbone_matches=evidence.core_policy.backbone_matches,
        backbone_share=(
            evidence.core_policy.backbone_matches / evidence.eligible_player_matches
        ),
        core_joint_matches=joint_matches,
        core_joint_share=joint_share,
        median_final_net_worth=median_net_worth,
        core_target_cost=target_cost,
        build_tag_ids=build_identity.tag_ids,
        build_tag_classes=build_identity.tag_classes,
        build_tag_labels=build_identity.tag_labels,
        build_tag_catalog_sha256=build_identity.catalog_sha256,
        build_archetype=build_identity.archetype,
        analysis_start_timestamp=_analysis_start_timestamp(manifest),
        as_of_timestamp=as_of_timestamp,
    )
