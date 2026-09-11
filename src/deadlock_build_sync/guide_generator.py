"""Validate generator identity without importing analysis dependencies."""

from __future__ import annotations

import hashlib
import json
import math
from typing import TYPE_CHECKING

from .artifacts import ArtifactError
from .build_evidence_values import _require_integer, _require_sha256
from .purchase_windows import wilson_score_interval
from .snapshot import sha256_json
from .value_validation import object_dict, object_list

if TYPE_CHECKING:
    from .build_evidence_types import HeroBuildEvidence

GENERATOR_NAMES = ("current", "beam")
BEAM_SCHEMA_VERSION = 13
BEAM_METHOD_VERSION = "eclat-leiden-beam16-v2"
BEAM_SETTINGS: dict[str, int | float] = {
    "width": 16,
    "prior_strength": 1000.0,
    "uncertainty_multiplier": 0.5,
    "cost_exponent": 0.5,
    "discount": 0.97,
    "minimum_item_support": 30,
    "minimum_core_support": 200,
    "maximum_core_cost": 19200,
    "minimum_group_similarity": 0.5,
    "ownership_before_seconds": 1200,
}


def generator_record() -> dict[str, object]:
    return {
        "name": "beam",
        "version": BEAM_METHOD_VERSION,
        "settings": dict(BEAM_SETTINGS),
        "settings_sha256": sha256_json(BEAM_SETTINGS),
    }


def require_generator(requested: str, actual: str) -> None:
    if requested not in GENERATOR_NAMES or requested != actual:
        raise ArtifactError(
            f"Requested generator {requested} differs from artifact generator {actual}. "
            "Use the matching artifact directory or refresh evidence."
        )


def validate_generator_header(value: object) -> None:
    if value != generator_record():
        raise ArtifactError("Beam generator settings or version differ")


def validate_generator_group(
    members: list[HeroBuildEvidence], default: HeroBuildEvidence
) -> None:
    if not all(build.generator for build in members):
        raise ArtifactError("Beam group lacks generator records")
    reference = default.generator.get("variant_id")
    for build in members:
        record = build.generator
        if record.get("default_variant_id") != reference:
            raise ArtifactError(
                "Beam group has inconsistent default variant references"
            )
        beam = record.get("effective") == "beam"
        if beam != (build.discovery.get("method") == "eclat_leiden_beam"):
            raise ArtifactError(
                "Beam effective generator differs from its discovery method"
            )
        if beam and record.get("frozen_sha256") != build.discovery.get("frozen_sha256"):
            raise ArtifactError("Beam path differs from its frozen candidate family")
        if record.get("frozen_sha256") != default.generator.get("frozen_sha256"):
            raise ArtifactError("Beam group contains different candidate families")
    if 1 not in (object_list(default.generator.get("states")) or []):
        raise ArtifactError("Beam default requires even-state support")


def validate_generator_path(
    value: object, *, group: str, core: tuple[int, ...], hero: int
) -> dict[str, object]:
    record = object_dict(value)
    if record is None:
        raise ArtifactError("Beam path has no generator evidence")
    if (
        record.get("group_id") != group
        or record.get("baseline_path_id") != group
        or record.get("effective") not in GENERATOR_NAMES
    ):
        raise ArtifactError("Beam path has inconsistent group or generator identity")
    if record.get("core") != sorted(core):
        raise ArtifactError("Beam generator core differs from the admitted core")
    expected = (
        f"{hero}-" + hashlib.sha256(json.dumps(sorted(core)).encode()).hexdigest()[:16]
    )
    if record.get("variant_id") != expected:
        raise ArtifactError("Beam variant identity differs from its core")
    for key in (
        "variant_id",
        "default_variant_id",
        "baseline_path_id",
        "frozen_sha256",
    ):
        if not isinstance(record.get(key), str) or not record[key]:
            raise ArtifactError(f"Beam path lacks {key}")
    states = object_list(record.get("states"))
    if (
        not isinstance(states, list)
        or not states
        or any(type(state) is not int or state not in {0, 1, 2} for state in states)
        or len(states) != len(set(states))
    ):
        raise ArtifactError("Beam path has invalid wealth states")
    _validate_generator_scores(record, states)
    _require_sha256(record["frozen_sha256"], "beam candidate fingerprint")
    validate_state_evidence(record, states)
    return record


def _validate_generator_scores(record: dict[str, object], states: list[object]) -> None:
    if record["effective"] == "current":
        if (
            not isinstance(record.get("fallback_reason"), str)
            or not record["fallback_reason"]
        ):
            raise ArtifactError("Current fallback lacks its reason")
    else:
        scores = object_dict(record.get("scores"))
        if scores is None or set(scores) != {str(state) for state in states}:
            raise ArtifactError("Beam path scores differ from its wealth states")
        if any(
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(score)
            for score in scores.values()
        ):
            raise ArtifactError("Beam path has an invalid search score")


def validate_state_evidence(record: dict[str, object], states: list[object]) -> None:
    evidence = object_dict(record.get("state_evidence"))
    if evidence is None or set(evidence) != {str(state) for state in states}:
        raise ArtifactError("Beam statistics differ from the declared wealth states")
    for state in states:
        folds = object_dict(evidence[str(state)])
        if folds is None or set(folds) != {"discovery", "selection", "validation"}:
            raise ArtifactError("Beam statistics lack separate match partitions")
        for fold, value in folds.items():
            count = validate_state_row(value)
            if (
                record["effective"] == "beam"
                and fold == "discovery"
                and count < BEAM_SETTINGS["minimum_core_support"]
            ):
                raise ArtifactError("Beam core lacks matched discovery support")


def validate_state_row(value: object) -> int:
    row = object_dict(value)
    if row is None or row.get("ownership_before_seconds") != 1200:
        raise ArtifactError("Beam statistics use a different ownership checkpoint")
    count = _require_integer(row.get("owners"), "core owners")
    wins = _require_integer(row.get("wins"), "core wins")
    total = _require_integer(row.get("hero_matches"), "state hero matches")
    if wins > count or count > total:
        raise ArtifactError("Beam core statistics have inconsistent counts")
    lower, upper = wilson_score_interval(wins, count)
    expected = {
        "win_rate": wins / count if count else None,
        "lower_95": lower if count else None,
        "upper_95": upper if count else None,
    }
    for key, rate in expected.items():
        actual = row.get(key)
        if rate is None and actual is None:
            continue
        if (
            rate is None
            or isinstance(actual, bool)
            or not isinstance(actual, (int, float))
            or not math.isclose(actual, rate)
        ):
            raise ArtifactError(f"Beam core statistics have inconsistent {key}")
    baseline = row.get("hero_win_rate")
    if total == 0:
        if baseline is not None:
            raise ArtifactError("An empty hero sample cannot have a win rate")
        return count
    if (
        isinstance(baseline, bool)
        or not isinstance(baseline, (int, float))
        or not 0 <= baseline <= 1
    ):
        raise ArtifactError("Beam statistics have an invalid hero baseline")
    return count
