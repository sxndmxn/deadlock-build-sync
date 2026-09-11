"""Build small versioned generator records for regression tests."""

from copy import deepcopy

from deadlock_build_sync.guide_generator import (
    BEAM_METHOD_VERSION,
    BEAM_SCHEMA_VERSION,
    generator_record,
)
from deadlock_build_sync.offline.core_discovery import calculate_core_identity
from deadlock_build_sync.purchase_windows import wilson_score_interval
from deadlock_build_sync.value_validation import (
    integer,
    require_object_dict,
    require_object_list,
    require_object_rows,
)
from tests.build_evidence_fixtures import make_evidence_document


def make_state_evidence() -> dict[str, object]:
    lower, upper = wilson_score_interval(110, 200)
    row = {
        "owners": 200,
        "wins": 110,
        "win_rate": 0.55,
        "hero_matches": 400,
        "hero_win_rate": 0.5,
        "lower_95": lower,
        "upper_95": upper,
        "ownership_before_seconds": 1200,
    }
    return {
        "1": {fold: deepcopy(row) for fold in ("discovery", "selection", "validation")}
    }


def make_generator_path(
    core: tuple[int, ...], hero: int, group: str, *, effective: str = "beam"
) -> dict[str, object]:
    identity = calculate_core_identity(hero, list(core))
    return {
        "group_id": group,
        "core": sorted(core),
        "variant_id": identity,
        "default_variant_id": identity,
        "baseline_path_id": group,
        "frozen_sha256": "a" * 64,
        "states": [1],
        "scores": {"1": 0.1},
        "state_evidence": make_state_evidence(),
        "effective": effective,
        "fallback_reason": "No supported beam route"
        if effective == "current"
        else None,
    }


def make_beam_document(*, effective: str = "beam") -> dict[str, object]:
    document = make_evidence_document()
    document["schema_version"] = BEAM_SCHEMA_VERSION
    document["generator"] = generator_record()
    require_object_dict(document["method"])["version"] = BEAM_METHOD_VERSION
    for hero in require_object_rows(document["heroes"]):
        for build in require_object_rows(hero["builds"]):
            core = tuple(
                integer(item)
                for item in require_object_list(
                    require_object_dict(build["core_policy"])["default_item_ids"]
                )
            )
            build["generator"] = make_generator_path(
                core,
                integer(hero["hero_id"]),
                str(build["guide_group_id"]),
                effective=effective,
            )
            if effective == "beam":
                discovery = require_object_dict(build["discovery"])
                discovery["frozen_sha256"] = "a" * 64
                discovery["method"] = "eclat_leiden_beam"
                require_object_dict(discovery["path"])["method"] = "beam16"
                require_object_dict(build["sequence_policy"])["production_model"] = (
                    "beam16"
                )
    return document
