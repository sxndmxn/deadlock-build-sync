from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from .policy import BuildPolicy, PolicyError
from .snapshot import canonical_json, sha256_json


class ArtifactError(ValueError):
    """Raised when a reusable artifact is incomplete, stale, or incompatible."""


POLICY_ARTIFACT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class FingerprintLayers:
    mechanics: str
    analytics: str
    policy_basis: str
    narrative: str
    projection: str

    @classmethod
    def calculate(
        cls,
        *,
        mechanics: Any,
        analytics: Any,
        policy_basis: Any,
        narrative: Any,
        projection: Any,
    ) -> FingerprintLayers:
        """Calculate dependency-aware hashes for every artifact layer.

        Returns:
            Fingerprints whose downstream values include upstream identities.

        """
        mechanics_id = sha256_json(mechanics)
        analytics_id = sha256_json({
            "mechanics": mechanics_id,
            "analytics": analytics,
        })
        policy_id = sha256_json({
            "mechanics": mechanics_id,
            "analytics": analytics_id,
            "policy_basis": policy_basis,
        })
        narrative_id = sha256_json({
            "policy_basis": policy_id,
            "narrative": narrative,
        })
        projection_id = sha256_json({
            "policy_basis": policy_id,
            "projection": projection,
        })
        return cls(
            mechanics=mechanics_id,
            analytics=analytics_id,
            policy_basis=policy_id,
            narrative=narrative_id,
            projection=projection_id,
        )

    def as_dict(self) -> dict[str, str]:
        return {
            "mechanics": self.mechanics,
            "analytics": self.analytics,
            "policy_basis": self.policy_basis,
            "narrative": self.narrative,
            "projection": self.projection,
        }


@dataclass(frozen=True)
class ArtifactCompatibility:
    schema_version: int
    hero_id: int
    snapshot_id: str
    client_version: int
    match_mode: str
    rank_labels_sha256: str
    mechanics_sha256: str
    analytics_sha256: str
    policy_basis_sha256: str
    prompt_version: int | None = None
    model: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "hero_id": self.hero_id,
            "snapshot_id": self.snapshot_id,
            "client_version": self.client_version,
            "match_mode": self.match_mode,
            "rank_labels_sha256": self.rank_labels_sha256,
            "mechanics_sha256": self.mechanics_sha256,
            "analytics_sha256": self.analytics_sha256,
            "policy_basis_sha256": self.policy_basis_sha256,
            "prompt_version": self.prompt_version,
            "model": self.model,
        }

    def assert_reusable_with(self, expected: ArtifactCompatibility) -> None:
        """Require exact claim-bearing compatibility.

        Raises:
            ArtifactError: If any schema, cohort, source, evidence, or model field differs.

        """
        actual_payload = self.as_dict()
        expected_payload = expected.as_dict()
        differences = [
            key
            for key, expected_value in expected_payload.items()
            if actual_payload.get(key) != expected_value
        ]
        if differences:
            raise ArtifactError(
                "artifact is incompatible in: " + ", ".join(sorted(differences))
            )


def validate_hero_document(
    document: dict[str, Any],
    *,
    requested_hero_ids: set[int],
    allowed_exclusions: dict[int, str] | None = None,
) -> None:
    """Require exact requested-hero coverage and internally complete references.

    Raises:
        ArtifactError: If heroes are missing, extra, duplicated, malformed, or dangling.

    """
    heroes = document.get("heroes")
    if not isinstance(heroes, list):
        raise ArtifactError("artifact heroes must be an array")
    found: list[int] = []
    for hero in heroes:
        if not isinstance(hero, dict) or not isinstance(hero.get("hero_id"), int):
            raise ArtifactError("artifact contains a malformed hero")
        hero_id = int(hero["hero_id"])
        found.append(hero_id)
        evidence_ids = hero.get("evidence_ids", [])
        evidence = hero.get("evidence", [])
        if not isinstance(evidence_ids, list) or not isinstance(evidence, list):
            raise ArtifactError(f"hero {hero_id} has malformed evidence references")
        available = {
            row.get("claim_id")
            for row in evidence
            if isinstance(row, dict) and isinstance(row.get("claim_id"), str)
        }
        if not set(evidence_ids) <= available:
            raise ArtifactError(f"hero {hero_id} has dangling evidence references")
    if len(found) != len(set(found)):
        raise ArtifactError("artifact contains duplicate heroes")
    exclusions = allowed_exclusions or {}
    covered = set(found) | set(exclusions)
    missing = requested_hero_ids - covered
    extra = set(found) - requested_hero_ids
    empty_reasons = [
        hero_id for hero_id, reason in exclusions.items() if not reason.strip()
    ]
    if missing:
        raise ArtifactError(
            "artifact is missing heroes: " + ", ".join(map(str, sorted(missing)))
        )
    if extra:
        raise ArtifactError(
            "artifact contains extra heroes: " + ", ".join(map(str, sorted(extra)))
        )
    if empty_reasons:
        raise ArtifactError(
            "artifact exclusions need reasons: "
            + ", ".join(map(str, sorted(empty_reasons)))
        )


def build_policy_artifact(
    policies: list[BuildPolicy],
    *,
    snapshot_manifest: dict[str, Any],
    requested_hero_ids: set[int],
    exclusions: tuple[tuple[int, str], ...] = (),
) -> dict[str, Any]:
    """Build and validate a complete rich-policy sidecar document.

    Returns:
        Snapshot-bound policies plus exact requested-hero coverage.

    """
    document = {
        "schema_version": POLICY_ARTIFACT_SCHEMA_VERSION,
        "snapshot_manifest": snapshot_manifest,
        "requested_hero_ids": sorted(requested_hero_ids),
        "exclusions": [
            {"hero_id": hero_id, "reason": reason}
            for hero_id, reason in sorted(exclusions)
        ],
        "policies": [policy.as_dict() for policy in policies],
    }
    validate_policy_artifact(document)
    return document


def validate_policy_artifact(document: dict[str, Any]) -> None:
    """Validate policy round trips, snapshot compatibility, and roster coverage.

    Raises:
        ArtifactError: If any sidecar identity, policy, exclusion, or coverage fails.

    """
    if document.get("schema_version") != POLICY_ARTIFACT_SCHEMA_VERSION:
        raise ArtifactError("unsupported policy-artifact schema")
    manifest = document.get("snapshot_manifest")
    requested = document.get("requested_hero_ids")
    exclusions = document.get("exclusions")
    raw_policies = document.get("policies")
    header_checks = (
        isinstance(manifest, dict) and isinstance(manifest.get("snapshot_id"), str),
        isinstance(requested, list)
        and all(isinstance(hero_id, int) for hero_id in requested),
        isinstance(exclusions, list),
        isinstance(raw_policies, list),
    )
    if not all(header_checks):
        raise ArtifactError("policy artifact is missing manifest or coverage data")
    manifest_data = cast("dict[str, Any]", manifest)
    requested_ids = cast("list[int]", requested)
    exclusion_rows = cast("list[Any]", exclusions)
    policy_rows = cast("list[Any]", raw_policies)
    excluded: dict[int, str] = {}
    for exclusion in exclusion_rows:
        if (
            not isinstance(exclusion, dict)
            or not isinstance(exclusion.get("hero_id"), int)
            or not isinstance(exclusion.get("reason"), str)
            or not exclusion["reason"].strip()
        ):
            raise ArtifactError("policy artifact contains an invalid exclusion")
        excluded[int(exclusion["hero_id"])] = str(exclusion["reason"])
    decoded = []
    for raw_policy in policy_rows:
        if not isinstance(raw_policy, dict):
            raise ArtifactError("policy artifact contains a malformed policy")
        try:
            policy = BuildPolicy.from_dict(raw_policy)
        except PolicyError as error:
            raise ArtifactError(
                f"policy artifact contains an invalid policy: {error}"
            ) from error
        if policy.snapshot_id != manifest_data["snapshot_id"]:
            raise ArtifactError(f"hero {policy.hero_id} policy uses another snapshot")
        decoded.append(policy)
    hero_ids = [policy.hero_id for policy in decoded]
    if len(hero_ids) != len(set(hero_ids)):
        raise ArtifactError("policy artifact contains duplicate heroes")
    if set(hero_ids) & set(excluded):
        raise ArtifactError("policy artifact both includes and excludes a hero")
    if set(hero_ids) | set(excluded) != set(requested_ids):
        raise ArtifactError("policy artifact does not cover requested heroes")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_bytes(path: Path, content: bytes) -> None:
    """Durably replace one reusable artifact in its target directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as output:
            temporary = Path(output.name)
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(path)
        temporary = None
        _fsync_directory(path.parent)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def atomic_write_json(path: Path, document: dict[str, Any]) -> None:
    """Serialize canonical reviewable JSON through the durable artifact boundary."""
    content = json.dumps(document, indent=2, ensure_ascii=False).encode() + b"\n"
    atomic_write_bytes(path, content)


def load_fingerprinted_json(path: Path, *, expected_sha256: str) -> dict[str, Any]:
    """Read a JSON artifact and verify its exact bytes before admission.

    Returns:
        The decoded object.

    Raises:
        ArtifactError: If bytes, JSON, or root shape do not match expectations.

    """
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise ArtifactError(f"could not read artifact {path}: {error}") from error
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected_sha256:
        raise ArtifactError(f"artifact byte digest mismatch for {path}")
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ArtifactError(f"could not read artifact {path}: {error}") from error
    if not isinstance(decoded, dict):
        raise ArtifactError(f"artifact root is not an object: {path}")
    return decoded


def canonical_artifact_digest(document: dict[str, Any]) -> str:
    """Return the digest used for semantic artifact comparisons.

    Returns:
        SHA-256 of canonical JSON.

    """
    return hashlib.sha256(canonical_json(document)).hexdigest()
