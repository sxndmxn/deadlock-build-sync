from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol

from .artifact_bundle import ArtifactBundleError, load_artifact_guide_bundle
from .artifacts import ArtifactError, validate_policy_artifact
from .build_evidence import load_build_evidence
from .cache import CacheError, read_cache
from .narratives import NarrativeError, load_narrative_catalog
from .protobuf import hero_build_metadata
from .strategy_context import (
    StrategyContextError,
    validate_strategy_context_document,
)

if TYPE_CHECKING:
    from pathlib import Path

    from .api import Patch
    from .build_evidence import BuildEvidenceCatalog


class FreshnessError(ValueError):
    """Raised when generation inputs are not current."""


class FreshnessApi(Protocol):
    def resolve_client_version(self) -> int: ...

    def current_patch(self) -> Patch: ...


class FreshnessState(StrEnum):
    CURRENT = "current"
    STALE = "stale"
    MISSING = "missing"
    MALFORMED = "malformed"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class FreshnessStage:
    name: str
    state: FreshnessState
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"stage": self.name, "state": self.state.value, "detail": self.detail}


@dataclass(frozen=True)
class FreshnessReport:
    stages: tuple[FreshnessStage, ...]
    latest_client_version: int
    latest_patch: Patch

    @property
    def exit_code(self) -> int:
        if all(stage.state is FreshnessState.CURRENT for stage in self.stages):
            return 0
        if any(
            stage.state in {FreshnessState.MALFORMED, FreshnessState.UNAVAILABLE}
            for stage in self.stages
        ):
            return 1
        return 2

    def as_dict(self) -> dict[str, Any]:
        status = {
            0: "current",
            1: "invalid_or_unavailable",
            2: "regeneration_required",
        }[self.exit_code]
        return {
            "status": status,
            "latest_client_version": self.latest_client_version,
            "latest_patch": self.latest_patch.as_dict(),
            "stages": [stage.as_dict() for stage in self.stages],
        }


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("root must be an object")
    return value


def require_current_build_evidence(
    path: Path,
    api: FreshnessApi,
) -> BuildEvidenceCatalog:
    """Load evidence and reject a stale patch or client before later workflow stages.

    Returns:
        The validated, current evidence catalog.

    Raises:
        FreshnessError: If evidence is missing, malformed, or stale.

    """
    try:
        evidence = load_build_evidence(path)
    except (ArtifactError, OSError) as error:
        raise FreshnessError(f"build evidence is unavailable: {error}") from error
    latest_client = api.resolve_client_version()
    latest_patch = api.current_patch()
    stale: list[str] = []
    if evidence.client_version != latest_client:
        stale.append(
            f"client {evidence.client_version} != latest client {latest_client}"
        )
    if evidence.patch.get("identity") != latest_patch.identity:
        stale.append(
            f"patch {evidence.patch.get('identity', 'UNKNOWN')} != latest patch "
            f"{latest_patch.identity}"
        )
    if stale:
        raise FreshnessError("STALE — regeneration required: " + "; ".join(stale))
    return evidence


def _evidence_stage(
    path: Path,
    latest_client: int,
    latest_patch: Patch,
) -> tuple[FreshnessStage, BuildEvidenceCatalog | None]:
    if not path.is_file():
        return FreshnessStage("build_evidence", FreshnessState.MISSING, str(path)), None
    try:
        evidence = load_build_evidence(path)
    except (ArtifactError, OSError) as error:
        return (
            FreshnessStage("build_evidence", FreshnessState.MALFORMED, str(error)),
            None,
        )
    differences = []
    if evidence.client_version != latest_client:
        differences.append(f"client {evidence.client_version} != {latest_client}")
    if evidence.patch.get("identity") != latest_patch.identity:
        differences.append("patch identity differs")
    if differences:
        return (
            FreshnessStage(
                "build_evidence",
                FreshnessState.STALE,
                "; ".join(differences),
            ),
            evidence,
        )
    return (
        FreshnessStage(
            "build_evidence",
            FreshnessState.CURRENT,
            evidence.artifact_id,
        ),
        evidence,
    )


def _context_stage(
    path: Path,
    evidence: BuildEvidenceCatalog | None,
) -> tuple[FreshnessStage, dict[str, Any] | None]:
    if not path.is_file():
        return FreshnessStage(
            "strategy_context", FreshnessState.MISSING, str(path)
        ), None
    try:
        document = _read_json(path)
        validate_strategy_context_document(document)
    except (
        OSError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
        StrategyContextError,
    ) as error:
        return (
            FreshnessStage("strategy_context", FreshnessState.MALFORMED, str(error)),
            None,
        )
    manifest = document.get("snapshot_manifest")
    if not isinstance(manifest, dict):
        return (
            FreshnessStage(
                "strategy_context",
                FreshnessState.MALFORMED,
                "missing snapshot manifest",
            ),
            None,
        )
    if evidence is not None and (
        manifest.get("client_version") != evidence.client_version
        or (manifest.get("patch") or {}).get("identity")
        != evidence.patch.get("identity")
        or manifest.get("as_of_timestamp") != evidence.as_of_timestamp
    ):
        return (
            FreshnessStage(
                "strategy_context",
                FreshnessState.STALE,
                "snapshot differs from build evidence",
            ),
            document,
        )
    return (
        FreshnessStage(
            "strategy_context",
            FreshnessState.CURRENT,
            str(manifest.get("snapshot_id") or "validated"),
        ),
        document,
    )


def _policy_stage(path: Path, context: dict[str, Any] | None) -> FreshnessStage:
    if not path.is_file():
        return FreshnessStage("policies", FreshnessState.MISSING, str(path))
    try:
        document = _read_json(path)
        validate_policy_artifact(document)
    except (
        OSError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
        ArtifactError,
    ) as error:
        return FreshnessStage("policies", FreshnessState.MALFORMED, str(error))
    if context is not None and document.get("snapshot_manifest") != context.get(
        "snapshot_manifest"
    ):
        return FreshnessStage(
            "policies",
            FreshnessState.STALE,
            "snapshot differs from strategy context",
        )
    return FreshnessStage("policies", FreshnessState.CURRENT, "validated")


def _narrative_stage(path: Path, context: dict[str, Any] | None) -> FreshnessStage:
    if not path.is_file():
        return FreshnessStage("narratives", FreshnessState.MISSING, str(path))
    try:
        catalog = load_narrative_catalog(path)
    except (OSError, NarrativeError) as error:
        return FreshnessStage("narratives", FreshnessState.MALFORMED, str(error))
    manifest = context.get("snapshot_manifest") if context is not None else None
    if isinstance(manifest, dict) and catalog.snapshot_id != manifest.get(
        "snapshot_id"
    ):
        return FreshnessStage(
            "narratives",
            FreshnessState.STALE,
            "snapshot differs from strategy context",
        )
    return FreshnessStage("narratives", FreshnessState.CURRENT, "validated")


def _installed_stage(
    cache_path: Path | None,
    account_id: int | None,
    context: dict[str, Any] | None,
) -> FreshnessStage:
    if cache_path is None or account_id is None:
        return FreshnessStage(
            "installed_cache",
            FreshnessState.UNAVAILABLE,
            "Steam cache location was not supplied",
        )
    if context is None:
        return FreshnessStage(
            "installed_cache",
            FreshnessState.STALE,
            "strategy context is unavailable",
        )
    manifest = context.get("snapshot_manifest")
    snapshot_id = manifest.get("snapshot_id") if isinstance(manifest, dict) else None
    heroes = context.get("heroes")
    if not isinstance(heroes, list):
        return FreshnessStage(
            "installed_cache",
            FreshnessState.MALFORMED,
            "strategy context has no hero list",
        )
    expected = {
        int(hero["hero_id"]): str(hero["policy_id"])
        for hero in heroes
        if isinstance(hero, dict)
        and isinstance(hero.get("hero_id"), int)
        and isinstance(hero.get("policy_id"), str)
    }
    try:
        installed = _installed_descriptions(cache_path, account_id)
    except (CacheError, OSError, ValueError) as error:
        return FreshnessStage("installed_cache", FreshnessState.MALFORMED, str(error))
    detail = "validated"
    state = FreshnessState.CURRENT
    if set(installed) != set(expected):
        state = FreshnessState.STALE
        detail = "managed hero coverage differs from strategy context"
    else:
        mismatched = next(
            (
                hero_id
                for hero_id, policy_id in expected.items()
                if f"Snapshot: {snapshot_id}." not in installed[hero_id]
                or f"Policy: {policy_id}." not in installed[hero_id]
            ),
            None,
        )
        if mismatched is not None:
            state = FreshnessState.STALE
            detail = f"hero {mismatched} uses another snapshot or policy"
    return FreshnessStage("installed_cache", state, detail)


def _bundle_stage(artifact_directory: Path) -> FreshnessStage:
    paths = (
        artifact_directory / "strategy-context.json",
        artifact_directory / "policies.json",
        artifact_directory / "narratives.json",
        artifact_directory / "build-evidence.json",
    )
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        return FreshnessStage(
            "artifact_bundle",
            FreshnessState.MISSING,
            "missing: " + ", ".join(missing),
        )
    try:
        bundle = load_artifact_guide_bundle(*paths)
    except (ArtifactBundleError, ArtifactError, OSError, ValueError) as error:
        return FreshnessStage("artifact_bundle", FreshnessState.MALFORMED, str(error))
    return FreshnessStage(
        "artifact_bundle",
        FreshnessState.CURRENT,
        f"{len(bundle.guides)} reviewed guide(s) validated as one bundle",
    )


def _installed_descriptions(cache_path: Path, account_id: int) -> dict[int, str]:
    root = read_cache(cache_path)
    unpublished = root.get("Unpublished")
    if not isinstance(unpublished, list):
        raise CacheError("cache has no Unpublished list")
    installed: dict[int, str] = {}
    for blob in unpublished:
        if not isinstance(blob, bytes):
            continue
        metadata = hero_build_metadata(blob)
        description = metadata.description or ""
        if (
            metadata.author_account_id == account_id
            and "[deadlock-build-sync:v1]" in description
            and metadata.hero_id is not None
        ):
            installed[metadata.hero_id] = description
    return installed


def build_freshness_report(
    artifact_directory: Path,
    api: FreshnessApi,
    *,
    cache_path: Path | None = None,
    account_id: int | None = None,
) -> FreshnessReport:
    """Validate the complete artifact chain without mutating Steam or artifacts.

    Returns:
        A typed stage-by-stage freshness report.

    """
    latest_client = api.resolve_client_version()
    latest_patch = api.current_patch()
    evidence_stage, evidence = _evidence_stage(
        artifact_directory / "build-evidence.json",
        latest_client,
        latest_patch,
    )
    context_stage, context = _context_stage(
        artifact_directory / "strategy-context.json",
        evidence,
    )
    stages = (
        evidence_stage,
        context_stage,
        _policy_stage(artifact_directory / "policies.json", context),
        _narrative_stage(artifact_directory / "narratives.json", context),
        _bundle_stage(artifact_directory),
        _installed_stage(cache_path, account_id, context),
    )
    return FreshnessReport(stages, latest_client, latest_patch)
