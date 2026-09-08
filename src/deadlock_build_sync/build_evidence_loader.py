from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from .artifacts import ArtifactError
from .build_evidence_discovery import (
    REFRESH_INSTRUCTION,
    discovery_rank,
    exclusion_reason,
)
from .build_evidence_path import _parse_hero_builds
from .build_evidence_types import (
    BUILD_EVIDENCE_SCHEMA_VERSION,
    MAXIMUM_CORE_ITEM_COUNT,
    MAXIMUM_TIER_ADOPTION_DRIFT,
    METHOD_VERSION,
    MINIMUM_BACKBONE_ITEM_COUNT,
    MINIMUM_IMBUE_SHARE,
    MINIMUM_IMBUE_SUPPORT,
    MINIMUM_PURCHASE_WINDOW_COVERAGE,
    MINIMUM_PURCHASE_WINDOW_OBSERVATIONS,
    MINIMUM_TIER_ADOPTION,
    MINIMUM_TIER_SUPPORT,
    TIER_ITEM_COUNT,
    BuildEvidenceCatalog,
    HeroBuildEvidence,
)
from .build_evidence_values import _require_integer, _require_sha256
from .build_support import SUPPORT
from .snapshot import EpochBoundary, EpochSet, MatchMode, sha256_json
from .value_validation import object_dict, object_list, object_rows

if TYPE_CHECKING:
    from pathlib import Path

    from .ranks import RankCatalog, RankRange

_EXPECTED_METHOD: dict[str, object] = {
    "version": METHOD_VERSION,
    "minimum_core_item_count": MINIMUM_BACKBONE_ITEM_COUNT,
    "maximum_core_item_count": MAXIMUM_CORE_ITEM_COUNT,
    "minimum_core_support": SUPPORT.core_owners,
    "minimum_tier_support": MINIMUM_TIER_SUPPORT,
    "minimum_tier_adoption": MINIMUM_TIER_ADOPTION,
    "maximum_tier_adoption_drift": MAXIMUM_TIER_ADOPTION_DRIFT,
    "tier_item_count": TIER_ITEM_COUNT,
    "minimum_purchase_window_coverage": MINIMUM_PURCHASE_WINDOW_COVERAGE,
    "minimum_purchase_window_observations": MINIMUM_PURCHASE_WINDOW_OBSERVATIONS,
    "minimum_imbue_support": MINIMUM_IMBUE_SUPPORT,
    "minimum_imbue_share": MINIMUM_IMBUE_SHARE,
}


@dataclass(frozen=True)
class _BuildEvidenceHeader:
    artifact_id: str
    heroes: list[object]
    requested: list[object]
    patch: dict[str, object]
    cohort: dict[str, object]
    epochs: dict[str, object]


def _parse_epoch_boundary(value: object, label: str) -> EpochBoundary:
    if not isinstance(value, dict):
        raise ArtifactError(f"build evidence lacks the {label} epoch")
    identity = value.get("identity")
    if not isinstance(identity, str):
        raise ArtifactError(f"build evidence has an invalid {label} epoch")
    return EpochBoundary(
        identity,
        _require_integer(value.get("start_timestamp"), f"{label} epoch timestamp"),
    )


def _read_document(path: Path) -> tuple[bytes, dict[str, object]]:
    try:
        raw = path.read_bytes()
        loaded: object = json.loads(raw)
    except (OSError, json.JSONDecodeError) as error:
        raise ArtifactError(f"could not read build evidence {path}: {error}") from error
    document = object_dict(loaded)
    if document is None:
        raise ArtifactError("build evidence root must be an object")
    return raw, document


def _validate_method(document: dict[str, object]) -> None:
    method = object_dict(document.get("method"))
    if method is None or any(
        method.get(key) != value for key, value in _EXPECTED_METHOD.items()
    ):
        raise ArtifactError(
            f"build evidence uses an unsupported selection method. {REFRESH_INSTRUCTION}"
        )


def _parse_evidence_header(document: dict[str, object]) -> _BuildEvidenceHeader:
    artifact_id = document.get("artifact_id")
    payload = {key: value for key, value in document.items() if key != "artifact_id"}
    if not isinstance(artifact_id, str) or artifact_id != sha256_json(payload):
        raise ArtifactError("build evidence fingerprint does not match its contents")
    if document.get("schema_version") != BUILD_EVIDENCE_SCHEMA_VERSION:
        raise ArtifactError(f"unsupported build-evidence schema. {REFRESH_INSTRUCTION}")
    _validate_method(document)
    heroes = object_list(document.get("heroes"))
    requested = object_list(document.get("requested_hero_ids"))
    patch = object_dict(document.get("patch"))
    cohort = object_dict(document.get("cohort"))
    epochs = object_dict(document.get("epochs"))
    if heroes is None or requested is None:
        raise ArtifactError("build evidence has an incomplete identity header")
    if patch is None or not isinstance(patch.get("identity"), str):
        raise ArtifactError("build evidence has an incomplete identity header")
    if cohort is None or epochs is None:
        raise ArtifactError("build evidence has an incomplete identity header")
    return _BuildEvidenceHeader(artifact_id, heroes, requested, patch, cohort, epochs)


def _parse_catalog_heroes(
    raw_heroes: list[object], requested: list[object]
) -> tuple[
    dict[int, tuple[HeroBuildEvidence, ...]],
    dict[int, HeroBuildEvidence],
    frozenset[int],
]:
    hero_rows = tuple(_parse_hero_builds(row) for row in raw_heroes)
    hero_builds = dict(hero_rows)
    if len(hero_builds) != len(hero_rows):
        raise ArtifactError("build evidence contains duplicate heroes")
    by_id = {
        hero_id: min(builds, key=lambda build: discovery_rank(build.discovery))
        for hero_id, builds in hero_builds.items()
        if builds
    }
    requested_ids = frozenset(
        _require_integer(hero_id, "requested hero id", minimum=1)
        for hero_id in requested
    )
    if len(requested_ids) != len(requested):
        raise ArtifactError("build evidence contains duplicate requested heroes")
    if requested_ids != set(hero_builds):
        raise ArtifactError("build evidence does not exactly cover requested heroes")
    return hero_builds, by_id, requested_ids


def _validate_catalog(catalog: BuildEvidenceCatalog) -> None:
    _require_sha256(catalog.patch.get("identity"), "patch fingerprint")
    for hero in catalog.heroes.values():
        cohort = hero.cohort
        if cohort is not None and (
            cohort.maximum_badge != catalog.cohort.get("maximum_badge")
            or cohort.expansion_history[0]["minimum_badge"]
            != catalog.cohort.get("minimum_badge")
        ):
            raise ArtifactError("Hero ranks differ from the starting cohort")
    _ = catalog.as_of_timestamp
    if catalog.as_of_timestamp < catalog.epochs.analysis_start_timestamp:
        raise ArtifactError("build evidence as-of cutoff precedes an epoch boundary")
    for builds in catalog.hero_builds.values():
        groups: dict[str, list[HeroBuildEvidence]] = {}
        for build in builds:
            groups.setdefault(build.guide_group_id, []).append(build)
        for group_id, members in groups.items():
            default = min(members, key=lambda build: discovery_rank(build.discovery))
            if group_id != default.path_id:
                raise ArtifactError("Guide group differs from its frozen default")


def load_build_evidence(path: Path) -> BuildEvidenceCatalog:
    raw, document = _read_document(path)
    header = _parse_evidence_header(document)
    hero_builds, by_id, requested_ids = _parse_catalog_heroes(
        header.heroes, header.requested
    )
    catalog = BuildEvidenceCatalog(
        artifact_id=header.artifact_id,
        client_version=_require_integer(
            document.get("client_version"), "client version", minimum=1
        ),
        patch=header.patch,
        cohort=header.cohort,
        epochs=EpochSet(
            mechanics=_parse_epoch_boundary(
                header.epochs.get("mechanics"), "mechanics"
            ),
            matchmaking=_parse_epoch_boundary(
                header.epochs.get("matchmaking"), "matchmaking"
            ),
            map_objectives=_parse_epoch_boundary(
                header.epochs.get("map_objectives"), "map objectives"
            ),
            telemetry=_parse_epoch_boundary(
                header.epochs.get("telemetry"), "telemetry"
            ),
        ),
        rank_labels_sha256=_require_sha256(
            document.get("rank_labels_sha256"), "rank-label fingerprint"
        ),
        heroes_sha256=_require_sha256(
            document.get("heroes_sha256"), "hero fingerprint"
        ),
        items_sha256=_require_sha256(document.get("items_sha256"), "item fingerprint"),
        requested_hero_ids=requested_ids,
        heroes=by_id,
        hero_builds=hero_builds,
        raw_bytes=raw,
        exclusions={
            _require_integer(
                row["hero_id"], "excluded hero id", minimum=1
            ): exclusion_reason(row.get("exclusion"))
            for row in object_rows(header.heroes) or []
            if row.get("builds") == []
        },
    )
    _validate_catalog(catalog)
    assets = object_rows(document.get("mechanics_assets"))
    if not assets or sha256_json(assets) != catalog.items_sha256:
        raise ArtifactError(
            f"Build evidence has no compatible mechanics assets. {REFRESH_INSTRUCTION}"
        )
    return replace(catalog, assets=tuple(assets))


@dataclass(frozen=True)
class BuildEvidenceIdentity:
    patch_identity: str
    client_version: int
    as_of_timestamp: int
    match_mode: MatchMode
    rank_range: RankRange
    rank_catalog: RankCatalog
    heroes: list[dict[str, object]]
    assets: list[dict[str, object]]
    epochs: EpochSet


def assert_build_evidence_compatible(
    catalog: BuildEvidenceCatalog, expected: BuildEvidenceIdentity
) -> None:
    cohort_mode = str(catalog.cohort.get("match_mode") or "").casefold()
    cohort_game = str(catalog.cohort.get("game_mode") or "").casefold()
    differences = []
    checks = {
        "patch": catalog.patch.get("identity") == expected.patch_identity,
        "client_version": catalog.client_version == expected.client_version,
        "as_of_timestamp": catalog.as_of_timestamp == expected.as_of_timestamp,
        "match_mode": cohort_mode == expected.match_mode.value,
        "game_mode": cohort_game == "normal",
        "minimum_badge": catalog.cohort.get("minimum_badge")
        == expected.rank_range.minimum.badge_id,
        "maximum_badge": catalog.cohort.get("maximum_badge")
        == expected.rank_range.maximum.badge_id,
        "rank_labels": catalog.rank_labels_sha256 == expected.rank_catalog.sha256,
        "heroes": catalog.heroes_sha256 == sha256_json(expected.heroes),
        "items": catalog.items_sha256 == sha256_json(expected.assets),
        "epochs": catalog.epochs == expected.epochs,
    }
    differences.extend(key for key, compatible in checks.items() if not compatible)
    if differences:
        raise ArtifactError(
            "build evidence is incompatible in: " + ", ".join(sorted(differences))
        )
