from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class MatchMode(StrEnum):
    """Supported public matchmaking populations."""

    RANKED = "ranked"
    UNRANKED = "unranked"

    @classmethod
    def parse(cls, value: str) -> MatchMode:
        try:
            return cls(value.strip().casefold())
        except ValueError as error:
            choices = ", ".join(mode.value for mode in cls)
            raise ValueError(
                f"unknown match mode {value!r}; choose {choices}"
            ) from error


class EvidenceUnit(StrEnum):
    """Units carried by exported observational evidence."""

    ASSET = "asset"
    PURCHASE_EVENT = "purchase_event"
    ELIGIBLE_APPEARANCE = "eligible_player_appearance"
    ABILITY_PATH = "ability_path"
    ABILITY_DECISION = "ability_decision_reached"
    HERO_APPEARANCE = "hero_appearance"
    HERO_ENEMY_PAIR = "hero_enemy_pair"
    GAME = "game"
    ITEM_FLOW_PAIR = "adjacent_phase_item_pair"


@dataclass(frozen=True)
class EpochBoundary:
    """Named start of one independently versioned evidence regime."""

    identity: str
    start_timestamp: int

    def __post_init__(self) -> None:
        """Validate identity and timestamp.

        Raises:
            ValueError: If the epoch identity or timestamp is invalid.

        """
        if not self.identity.strip():
            raise ValueError("epoch identity must not be empty")
        if self.start_timestamp < 0:
            raise ValueError("epoch start timestamp must be non-negative")

    def as_dict(self) -> dict[str, str | int]:
        return {
            "identity": self.identity,
            "start_timestamp": self.start_timestamp,
        }


@dataclass(frozen=True)
class EpochSet:
    """Independent boundaries that define one coherent evidence regime."""

    mechanics: EpochBoundary
    matchmaking: EpochBoundary
    map_objectives: EpochBoundary
    telemetry: EpochBoundary

    def as_dict(self) -> dict[str, dict[str, str | int]]:
        return {
            "mechanics": self.mechanics.as_dict(),
            "matchmaking": self.matchmaking.as_dict(),
            "map_objectives": self.map_objectives.as_dict(),
            "telemetry": self.telemetry.as_dict(),
        }

    @property
    def analysis_start_timestamp(self) -> int:
        return max(
            self.mechanics.start_timestamp,
            self.matchmaking.start_timestamp,
            self.map_objectives.start_timestamp,
            self.telemetry.start_timestamp,
        )


@dataclass(frozen=True)
class OutcomePolicy:
    """Outcome exclusions requested by the build-analysis contract."""

    exclude_not_scored: bool = True
    exclude_penalized: bool = True
    exclude_party_penalized: bool = True
    exclude_abandoned: bool = True
    exclude_unrewarded: bool = True
    exclude_low_priority: bool = True
    exclude_new_player: bool = True

    def as_dict(self, *, enforced: bool) -> dict[str, bool]:
        return {
            "exclude_not_scored": self.exclude_not_scored,
            "exclude_penalized": self.exclude_penalized,
            "exclude_party_penalized": self.exclude_party_penalized,
            "exclude_abandoned": self.exclude_abandoned,
            "exclude_unrewarded": self.exclude_unrewarded,
            "exclude_low_priority": self.exclude_low_priority,
            "exclude_new_player": self.exclude_new_player,
            "enforced_by_source": enforced,
        }


def canonical_json(value: Any) -> bytes:
    """Encode a value for stable evidence fingerprints.

    Returns:
        Stable UTF-8 JSON bytes.

    """
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


@dataclass(frozen=True)
class EvidenceRecord:
    """One immutable API response and its declared analytic semantics."""

    path: str
    parameters: dict[str, Any]
    fetched_at: str
    sha256: str
    byte_count: int
    unit: EvidenceUnit
    backend_grain: str
    fallback_behavior: str
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "parameters": self.parameters,
            "fetched_at": self.fetched_at,
            "sha256": self.sha256,
            "byte_count": self.byte_count,
            "unit": self.unit.value,
            "backend_grain": self.backend_grain,
            "fallback_behavior": self.fallback_behavior,
            "warnings": list(self.warnings),
        }

    def identity_dict(self) -> dict[str, Any]:
        """Return stable source identity without wall-clock fetch metadata.

        Returns:
            The request, response, and semantics fields that define compatibility.

        """
        payload = self.as_dict()
        payload.pop("fetched_at")
        return payload


@dataclass
class EvidenceRecorder:
    """Collect exact request/response identities for one generation run."""

    records: list[EvidenceRecord] = field(default_factory=list)
    _semantics: dict[str, tuple[EvidenceUnit, str, str, tuple[str, ...]]] = field(
        default_factory=dict,
        repr=False,
    )

    def declare(
        self,
        path: str,
        *,
        unit: EvidenceUnit,
        backend_grain: str,
        fallback_behavior: str = "none",
        warnings: tuple[str, ...] = (),
    ) -> None:
        if not backend_grain.strip():
            raise ValueError("backend grain must not be empty")
        if not fallback_behavior.strip():
            raise ValueError("fallback behavior must not be empty")
        self._semantics[path] = (
            unit,
            backend_grain,
            fallback_behavior,
            warnings,
        )

    def record(
        self,
        path: str,
        parameters: dict[str, Any],
        raw: bytes,
        *,
        fetched_at: datetime | None = None,
    ) -> EvidenceRecord:
        semantics = self._semantics.get(path)
        if semantics is None:
            raise ValueError(f"evidence semantics were not declared for {path}")
        record = EvidenceRecord(
            path=path,
            parameters=dict(sorted(parameters.items())),
            fetched_at=(fetched_at or datetime.now(UTC)).isoformat(),
            sha256=hashlib.sha256(raw).hexdigest(),
            byte_count=len(raw),
            unit=semantics[0],
            backend_grain=semantics[1],
            fallback_behavior=semantics[2],
            warnings=semantics[3],
        )
        self.records.append(record)
        return record


@dataclass(frozen=True)
class SnapshotManifest:
    """Frozen source, cohort, and request identities for a generated policy."""

    client_version: int
    as_of_timestamp: int
    created_at: str
    match_mode: MatchMode
    game_mode: str
    rank_range: dict[str, object]
    rank_labels_sha256: str
    patch: dict[str, Any]
    epochs: EpochSet
    outcome_policy: OutcomePolicy
    outcome_policy_enforced: bool
    records: tuple[EvidenceRecord, ...]
    build_tags_sha256: str = ""
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate cross-field snapshot invariants.

        Raises:
            ValueError: If the manifest is incomplete or temporally incoherent.

        """
        if self.client_version <= 0:
            raise ValueError("client version must be positive")
        if self.game_mode != "normal":
            raise ValueError("only the normal Deadlock ruleset is supported")
        if self.as_of_timestamp < self.epochs.analysis_start_timestamp:
            raise ValueError("as-of cutoff precedes a required epoch boundary")
        if not self.records:
            raise ValueError("snapshot manifest must contain source records")
        if len(self.build_tags_sha256) != 64:
            raise ValueError("snapshot manifest has no valid build-tag fingerprint")

    def _payload(self, *, identity: bool = False) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "client_version": self.client_version,
            "as_of_timestamp": self.as_of_timestamp,
            **({} if identity else {"created_at": self.created_at}),
            "match_mode": self.match_mode.value,
            "game_mode": self.game_mode,
            "rank_range": self.rank_range,
            "rank_labels_sha256": self.rank_labels_sha256,
            "build_tags_sha256": self.build_tags_sha256,
            "patch": self.patch,
            "epochs": self.epochs.as_dict(),
            "outcome_policy": self.outcome_policy.as_dict(
                enforced=self.outcome_policy_enforced
            ),
            "records": [
                record.identity_dict() if identity else record.as_dict()
                for record in self.records
            ],
            "warnings": list(self.warnings),
        }

    @property
    def snapshot_id(self) -> str:
        return sha256_json(self._payload(identity=True))

    def as_dict(self) -> dict[str, Any]:
        payload = self._payload()
        payload["snapshot_id"] = self.snapshot_id
        return payload
