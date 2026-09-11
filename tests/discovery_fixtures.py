"""Small frozen discovery records for artifact-contract regression tests."""

from __future__ import annotations

from copy import deepcopy

from deadlock_build_sync.build_evidence import METHOD_VERSION
from deadlock_build_sync.snapshot import sha256_json
from deadlock_build_sync.value_validation import (
    integer,
    require_object_dict,
    require_object_list,
    require_object_rows,
)


def make_discovery_record(core: list[int], path: list[int]) -> dict[str, object]:
    adjusted = {
        "core_overlap": 200,
        "overlap_share": 1.0,
        "difference": 0.20,
        "lower_95": 0.10,
        "standard_error": 0.01,
        "p_greater": 0.00001,
    }
    outcome = {
        "owners": 200,
        "wins": 150,
        "win_rate": 0.75,
        "joint_lift": 2.0,
        "win_lower_95": 0.65,
        "win_p_greater_half": 0.00001,
        "adjusted": adjusted,
        "adjusted_lower_family": 0.10,
    }
    ordered = {"owners": 200, "ordered_owners": 100, "share": 0.5, "passes": True}
    return {
        "method": "eclat_leiden_pairwise",
        "items": sorted(core),
        "selection_rank": 0,
        "discovery_support": 200,
        "evidence_status": "outcome_supported",
        "evidence_limitations": [],
        "test_evaluated": False,
        "selection": outcome,
        "validation": outcome,
        "selection_rejections": [],
        "rejections": [],
        "hypotheses": 1,
        "path": {
            "method": "pairwise",
            "order": list(core),
            "discovery": ordered,
            "selection": ordered,
            "legal": True,
            "admitted_before_validation": True,
        },
        "order_validation": ordered,
        "frozen_guide": {"ready": True, "path": list(path), "bounds": {}},
    }


def make_current_evidence_document(
    document: dict[str, object], assets: list[dict[str, object]]
) -> dict[str, object]:
    document["schema_version"] = 12
    require_object_dict(document["method"])["version"] = METHOD_VERSION
    require_object_dict(document["method"])["minimum_core_item_count"] = 3
    require_object_dict(document["method"])["minimum_core_support"] = 100
    document["mechanics_assets"] = assets
    document["items_sha256"] = sha256_json(assets)
    cohort = require_object_dict(document["cohort"])
    for hero in require_object_rows(document["heroes"]):
        hero["cohort"] = {
            "minimum_badge": cohort["minimum_badge"],
            "maximum_badge": cohort["maximum_badge"],
            "rank_expansion": "auto",
            "expansion_history": [
                {
                    "minimum_badge": cohort["minimum_badge"],
                    "maximum_badge": cohort["maximum_badge"],
                    "discovery_rows": 600,
                    "selection_rows": 200,
                    "candidate_count": 3,
                    "discovery_owners": 200,
                    "selection_owners": 200,
                    "supported_builds": len(require_object_rows(hero["builds"])),
                    "reason": "supported build available",
                }
            ],
        }
        for build in require_object_rows(hero["builds"]):
            build["guide_group_id"] = build["path_id"]
            core = [
                integer(item)
                for item in require_object_list(
                    require_object_dict(build["core_policy"])["default_item_ids"]
                )
            ]
            path = [
                integer(item)
                for item in require_object_list(
                    require_object_dict(build["sequence_policy"])[
                        "component_expanded_default_path"
                    ]
                )
            ]
            build["discovery"] = make_discovery_record(core, path)
            tier = require_object_dict(build["tier_policy"])
            pool = require_object_dict(tier["item_ids_by_tier"])
            statistics = {
                str(integer(item)): {"buyers": 40, "adoption": 0.2}
                for items in pool.values()
                for item in require_object_list(items)
            }
            tier.update({"source_fold": "discovery", "statistics": statistics})
            require_object_dict(
                require_object_dict(build["discovery"])["frozen_guide"]
            ).update({
                "pool": deepcopy(pool),
                "pool_statistics": deepcopy(statistics),
                "discovery_buyers": 200,
                "purchase_timing": deepcopy(build.get("purchase_timing")),
            })
    document.pop("artifact_id", None)
    document["artifact_id"] = sha256_json(document)
    return document


def make_hero_cohort() -> dict[str, object]:
    return {
        "minimum_badge": 61,
        "maximum_badge": 115,
        "rank_expansion": "auto",
        "expansion_history": [
            {
                "minimum_badge": minimum,
                "maximum_badge": 115,
                "discovery_rows": 500,
                "selection_rows": 200,
                "candidate_count": 3,
                "discovery_owners": 100,
                "selection_owners": 90 if minimum == 71 else 100,
                "supported_builds": 0 if minimum == 71 else 1,
                "reason": "no supported legal path"
                if minimum == 71
                else "supported build available",
            }
            for minimum in (71, 61)
        ],
    }
