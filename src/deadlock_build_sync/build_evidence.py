from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

from .artifacts import ArtifactError
from .mechanics import (
    InventoryState,
    ItemGraph,
    MechanicsError,
    purchase_item,
    schedule_component_path,
)
from .snapshot import EpochBoundary, EpochSet, MatchMode, sha256_json

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from .ranks import RankCatalog, RankRange

BUILD_EVIDENCE_SCHEMA_VERSION = 2

type _SequencePolicyDocument = dict[str, Any]
type _SituationalBranchDocument = dict[str, Any]
type _SituationalPolicyDocument = dict[str, Any]


CORE_ITEM_COUNT = 8
CORE_CANDIDATE_LIMIT = 64
TIER_ITEM_COUNT = 10
MINIMUM_TIER_SUPPORT = 20
MINIMUM_CORE_SUPPORT = 20
METHOD_VERSION = "reconstructed-final-inventory-v3"
SEQUENCE_POLICY_VERSION = 3
SITUATIONAL_POLICY_VERSION = 1
MAX_SITUATIONAL_BRANCHES = 7
MAX_COMPARATIVE_INTERVAL_WIDTH = 0.10
SEQUENCE_LEVELS = (
    "first_previous_position",
    "previous_position",
    "position",
    "popularity",
)
THREAT_CLASSES = frozenset({
    "healing",
    "bullet_pressure",
    "spirit_pressure",
    "control",
    "mobility_escape",
    "ally_protection",
    "active_slot_burden",
})
MECHANIC_RESPONSE_THREATS = {
    "hard_control": "control",
    "healing": "healing",
    "bullet_pressure": "bullet_pressure",
    "spirit_burst": "spirit_pressure",
    "mobility_denial": "mobility_escape",
    "ally_protection": "ally_protection",
}


@dataclass(frozen=True)
class ItemEvidence:
    item_id: int
    item: str
    tier: int
    cost: int
    slot: str
    active: bool
    adopter_matches: int
    eligible_player_matches: int
    purchase_events: int
    wins: int
    adoption: float
    observed_outcome_rate: float
    median_buy_time_s: float
    median_valid_buy_net_worth: float | None
    buy_net_worth_q25: float | None
    buy_net_worth_q75: float | None
    valid_buy_net_worth_share: float


@dataclass(frozen=True)
class CoreCandidate:
    item_ids: tuple[int, ...]
    joint_matches: int


@dataclass(frozen=True)
class SequenceTransition:
    level: str
    first_item_id: int
    previous_item_id: int
    position: int
    next_item_id: int
    support: int
    context_support: int


@dataclass(frozen=True)
class SequencePolicy:
    default_path: tuple[int, ...]
    transitions: tuple[SequenceTransition, ...]
    minimum_support: int
    production_model: str
    evaluation: dict[str, Any]
    challenger: dict[str, Any]


@dataclass(frozen=True)
class SituationalBranch:
    threat: str
    item_id: int
    enemy_hero_id: int | None
    mechanic_ref: str
    comparator: str
    comparator_item_id: int
    comparison_support: int
    same_opportunity: bool
    support: int
    effective_support: float
    overlap: float
    stable: bool
    comparative_interval: tuple[float, float]
    trigger: str
    replacement: str
    execution: str
    failure_condition: str


@dataclass(frozen=True)
class SituationalPolicy:
    branches: tuple[SituationalBranch, ...]
    abstentions: tuple[str, ...]


@dataclass(frozen=True)
class HeroBuildEvidence:
    hero_id: int
    hero: str
    eligible_player_matches: int
    median_final_net_worth: int
    core_candidates: tuple[CoreCandidate, ...]
    items: tuple[ItemEvidence, ...]
    sequence_policy: SequencePolicy | None = None
    situational_policy: SituationalPolicy | None = None


@dataclass(frozen=True)
class SelectedHeroBuild:
    hero_id: int
    core: tuple[ItemEvidence, ...]
    core_purchase_path: tuple[ItemEvidence, ...]
    tiers: dict[int, tuple[ItemEvidence, ...]]
    core_joint_matches: int
    core_joint_share: float
    median_final_net_worth: int
    core_target_cost: int


@dataclass(frozen=True)
class BuildEvidenceCatalog:
    artifact_id: str
    client_version: int
    patch: dict[str, Any]
    cohort: dict[str, Any]
    epochs: EpochSet
    rank_labels_sha256: str
    heroes_sha256: str
    items_sha256: str
    requested_hero_ids: frozenset[int]
    heroes: dict[int, HeroBuildEvidence]
    raw_bytes: bytes

    @property
    def as_of_timestamp(self) -> int:
        value = self.cohort.get("as_of")
        if not isinstance(value, str):
            raise ArtifactError("build evidence has no frozen as-of timestamp")
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as error:
            raise ArtifactError(
                "build evidence has an invalid as-of timestamp"
            ) from error
        if parsed.tzinfo is None:
            raise ArtifactError("build evidence as-of timestamp lacks a timezone")
        return int(parsed.timestamp())


def _required_int(value: object, label: str, *, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ArtifactError(f"build evidence has invalid {label}")
    return value


def _required_float(
    value: object, label: str, *, minimum: float = 0.0, maximum: float | None = None
) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or float(value) < minimum
        or (maximum is not None and float(value) > maximum)
    ):
        raise ArtifactError(f"build evidence has invalid {label}")
    return float(value)


def _required_bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ArtifactError(f"build evidence has invalid {label}")
    return value


def _optional_float(value: object, label: str) -> float | None:
    return None if value is None else _required_float(value, label)


def _required_sha256(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ArtifactError(f"build evidence has invalid {label}")
    return value


def _item(value: object, hero_id: int) -> ItemEvidence:
    if not isinstance(value, dict):
        raise ArtifactError(f"hero {hero_id} has a malformed item evidence row")
    item_id = _required_int(value.get("item_id"), "item id", minimum=1)
    name = value.get("item")
    slot = value.get("slot")
    if (
        not isinstance(name, str)
        or not name.strip()
        or not isinstance(slot, str)
        or not slot.strip()
    ):
        raise ArtifactError(f"hero {hero_id} item {item_id} lacks identity")
    adopter_matches = _required_int(value.get("adopter_matches"), "adopter matches")
    eligible = _required_int(
        value.get("eligible_player_matches"), "eligible player matches", minimum=1
    )
    purchase_events = _required_int(value.get("purchase_events"), "purchase events")
    wins = _required_int(value.get("wins"), "wins")
    if (
        adopter_matches > eligible
        or purchase_events < adopter_matches
        or wins > adopter_matches
    ):
        raise ArtifactError(f"hero {hero_id} item {item_id} has impossible counts")
    adoption = _required_float(value.get("adoption"), "adoption", maximum=1.0)
    outcome = _required_float(
        value.get("observed_outcome_rate"), "observed outcome", maximum=1.0
    )
    if not math.isclose(adoption, adopter_matches / eligible, abs_tol=1e-9):
        raise ArtifactError(f"hero {hero_id} item {item_id} adoption is inconsistent")
    expected_outcome = wins / adopter_matches if adopter_matches else 0.0
    if not math.isclose(outcome, expected_outcome, abs_tol=1e-9):
        raise ArtifactError(f"hero {hero_id} item {item_id} outcome is inconsistent")
    tier = _required_int(value.get("tier"), "item tier", minimum=1)
    if tier > 4:
        raise ArtifactError(f"hero {hero_id} item {item_id} has invalid tier")
    median_net_worth = _optional_float(
        value.get("median_valid_buy_net_worth"), "median buy net worth"
    )
    q25 = _optional_float(value.get("buy_net_worth_q25"), "buy net worth q25")
    q75 = _optional_float(value.get("buy_net_worth_q75"), "buy net worth q75")
    if (
        (median_net_worth is None) != (q25 is None)
        or (median_net_worth is None) != (q75 is None)
        or (
            median_net_worth is not None
            and q25 is not None
            and q75 is not None
            and not q25 <= median_net_worth <= q75
        )
    ):
        raise ArtifactError(
            f"hero {hero_id} item {item_id} has invalid net-worth quantiles"
        )
    return ItemEvidence(
        item_id=item_id,
        item=name.strip(),
        tier=tier,
        cost=_required_int(value.get("cost"), "item cost"),
        slot=slot.strip().casefold(),
        active=_required_bool(value.get("active"), "active-item flag"),
        adopter_matches=adopter_matches,
        eligible_player_matches=eligible,
        purchase_events=purchase_events,
        wins=wins,
        adoption=adoption,
        observed_outcome_rate=outcome,
        median_buy_time_s=_required_float(
            value.get("median_buy_time_s"), "median buy time"
        ),
        median_valid_buy_net_worth=median_net_worth,
        buy_net_worth_q25=q25,
        buy_net_worth_q75=q75,
        valid_buy_net_worth_share=_required_float(
            value.get("valid_buy_net_worth_share"),
            "valid buy net worth share",
            maximum=1.0,
        ),
    )


def _sequence_transition(value: object, hero_id: int) -> SequenceTransition:
    if not isinstance(value, dict):
        raise ArtifactError(f"hero {hero_id} has a malformed sequence transition")
    level = value.get("level")
    if level not in SEQUENCE_LEVELS:
        raise ArtifactError(f"hero {hero_id} has an invalid sequence backoff level")
    support = _required_int(value.get("support"), "transition support", minimum=1)
    context_support = _required_int(
        value.get("context_support"),
        "transition context support",
        minimum=support,
    )
    return SequenceTransition(
        level=str(level),
        first_item_id=_required_int(value.get("first_item_id"), "first item id"),
        previous_item_id=_required_int(
            value.get("previous_item_id"), "previous item id"
        ),
        position=_required_int(value.get("position"), "purchase position"),
        next_item_id=_required_int(
            value.get("next_item_id"), "next item id", minimum=1
        ),
        support=support,
        context_support=context_support,
    )


def _sequence_policy(value: object, hero_id: int) -> SequencePolicy:
    if not isinstance(value, dict) or value.get("version") != SEQUENCE_POLICY_VERSION:
        raise ArtifactError(f"hero {hero_id} has no supported sequence policy")
    data = cast("_SequencePolicyDocument", value)
    raw_path = data.get("component_expanded_default_path")
    raw_transitions = data.get("transitions")
    evaluation = data.get("evaluation")
    challenger = data.get("challenger")
    production_model = data.get("production_model")
    if (
        not isinstance(raw_path, list)
        or not raw_path
        or not isinstance(raw_transitions, list)
        or not raw_transitions
        or not isinstance(evaluation, dict)
        or not isinstance(challenger, dict)
        or production_model != "deterministic_backoff"
    ):
        raise ArtifactError(f"hero {hero_id} has an incomplete sequence policy")
    path = tuple(
        _required_int(item_id, "default path item id", minimum=1)
        for item_id in raw_path
    )
    if len(path) != len(set(path)):
        raise ArtifactError(f"hero {hero_id} default path repeats an item")
    minimum_support = _required_int(
        data.get("minimum_support"), "sequence minimum support", minimum=20
    )
    transitions = tuple(_sequence_transition(row, hero_id) for row in raw_transitions)
    if any(row.support < minimum_support for row in transitions):
        raise ArtifactError(f"hero {hero_id} has a weak sequence transition")
    return SequencePolicy(
        path,
        transitions,
        minimum_support,
        str(production_model),
        evaluation,
        challenger,
    )


def _situational_branch(value: object, hero_id: int) -> SituationalBranch:
    if not isinstance(value, dict):
        raise ArtifactError(f"hero {hero_id} has a malformed situational branch")
    data = cast("_SituationalBranchDocument", value)
    threat = data.get("threat")
    enemy_hero_id = data.get("enemy_hero_id")
    text_fields = (
        "mechanic_ref",
        "comparator",
        "trigger",
        "replacement",
        "execution",
        "failure_condition",
    )
    if threat not in THREAT_CLASSES or any(
        not isinstance(data.get(field), str) or not str(data[field]).strip()
        for field in text_fields
    ):
        raise ArtifactError(f"hero {hero_id} has an incomplete situational branch")
    if enemy_hero_id is not None:
        enemy_hero_id = _required_int(enemy_hero_id, "enemy hero id", minimum=1)
    item_id = _required_int(data.get("item_id"), "situational item id", minimum=1)
    comparator_item_id = _required_int(
        data.get("comparator_item_id"),
        "situational comparator item id",
        minimum=1,
    )
    if comparator_item_id == item_id:
        raise ArtifactError(f"hero {hero_id} compares a situational item with itself")
    if not str(data["mechanic_ref"]).startswith(f"item/{item_id}/"):
        raise ArtifactError(
            f"hero {hero_id} has a mismatched situational mechanic reference"
        )
    same_opportunity = _required_bool(
        data.get("same_opportunity"), "situational same-opportunity gate"
    )
    comparison_support = _required_int(
        data.get("comparison_support"),
        "situational comparison support",
        minimum=20,
    )
    support = _required_int(data.get("support"), "situational support", minimum=20)
    effective = _required_float(
        data.get("effective_support"), "situational effective support", minimum=20
    )
    overlap = _required_float(data.get("overlap"), "situational overlap", maximum=1.0)
    stable = _required_bool(data.get("stable"), "situational stability")
    raw_interval = data.get("comparative_interval")
    if not isinstance(raw_interval, list) or len(raw_interval) != 2:
        raise ArtifactError(
            f"hero {hero_id} has no bounded situational comparative interval"
        )
    lower = _required_float(raw_interval[0], "situational interval lower")
    upper = _required_float(raw_interval[1], "situational interval upper")
    if lower > upper or lower <= 0 or upper - lower > MAX_COMPARATIVE_INTERVAL_WIDTH:
        raise ArtifactError(
            f"hero {hero_id} has an unqualified situational comparative interval"
        )
    if overlap < 0.5 or not stable or not same_opportunity:
        raise ArtifactError(
            f"hero {hero_id} contains an unqualified situational branch"
        )
    return SituationalBranch(
        threat=str(threat),
        item_id=item_id,
        enemy_hero_id=enemy_hero_id,
        mechanic_ref=str(data["mechanic_ref"]),
        comparator=str(data["comparator"]),
        comparator_item_id=comparator_item_id,
        comparison_support=comparison_support,
        same_opportunity=same_opportunity,
        support=support,
        effective_support=effective,
        overlap=overlap,
        stable=stable,
        comparative_interval=(lower, upper),
        trigger=str(data["trigger"]),
        replacement=str(data["replacement"]),
        execution=str(data["execution"]),
        failure_condition=str(data["failure_condition"]),
    )


def _situational_policy(value: object, hero_id: int) -> SituationalPolicy:
    if (
        not isinstance(value, dict)
        or value.get("version") != SITUATIONAL_POLICY_VERSION
    ):
        raise ArtifactError(f"hero {hero_id} has no supported situational policy")
    data = cast("_SituationalPolicyDocument", value)
    branches = data.get("branches")
    abstentions = data.get("abstentions")
    vocabulary = data.get("threat_vocabulary")
    if (
        not isinstance(branches, list)
        or not isinstance(abstentions, list)
        or vocabulary != sorted(THREAT_CLASSES)
    ):
        raise ArtifactError(f"hero {hero_id} has an incomplete situational policy")
    if len(branches) > MAX_SITUATIONAL_BRANCHES:
        raise ArtifactError(f"hero {hero_id} has too many situational branches")
    if not all(isinstance(reason, str) and reason.strip() for reason in abstentions):
        raise ArtifactError(f"hero {hero_id} has an invalid situational abstention")
    admitted = tuple(_situational_branch(row, hero_id) for row in branches)
    identities = [
        (branch.threat, branch.enemy_hero_id, branch.item_id) for branch in admitted
    ]
    if len(identities) != len(set(identities)):
        raise ArtifactError(f"hero {hero_id} has duplicate situational branches")
    item_ids = [branch.item_id for branch in admitted]
    if len(item_ids) != len(set(item_ids)):
        raise ArtifactError(f"hero {hero_id} repeats a situational item")
    if not admitted and not abstentions:
        raise ArtifactError(f"hero {hero_id} has no situational result")
    return SituationalPolicy(
        admitted,
        tuple(cast("list[str]", abstentions)),
    )


def _hero_items(
    raw_items: Sequence[object],
    hero_id: int,
    eligible: int,
) -> tuple[tuple[ItemEvidence, ...], list[int]]:
    items = tuple(_item(row, hero_id) for row in raw_items)
    item_ids = [item.item_id for item in items]
    if len(item_ids) != len(set(item_ids)):
        raise ArtifactError(f"hero {hero_id} has duplicate item evidence")
    if any(item.eligible_player_matches != eligible for item in items):
        raise ArtifactError(f"hero {hero_id} item denominators disagree")
    return items, item_ids


def _core_candidate(
    row: object,
    hero_id: int,
    item_ids: list[int],
    eligible: int,
) -> CoreCandidate:
    if not isinstance(row, dict):
        raise ArtifactError(f"hero {hero_id} has a malformed core candidate")
    raw_item_ids = row.get("item_ids")
    if not isinstance(raw_item_ids, list):
        raise ArtifactError(f"hero {hero_id} has a malformed core candidate")
    candidate_ids = tuple(
        _required_int(item_id, "core item id", minimum=1) for item_id in raw_item_ids
    )
    matches = _required_int(row.get("joint_matches"), "core support")
    if (
        len(candidate_ids) != CORE_ITEM_COUNT
        or len(set(candidate_ids)) != CORE_ITEM_COUNT
        or tuple(sorted(candidate_ids)) != candidate_ids
        or not set(candidate_ids) <= set(item_ids)
        or matches < MINIMUM_CORE_SUPPORT
        or matches > eligible
    ):
        raise ArtifactError(f"hero {hero_id} has an invalid core candidate")
    return CoreCandidate(candidate_ids, matches)


def _core_candidates(
    raw_candidates: Sequence[object],
    hero_id: int,
    item_ids: list[int],
    eligible: int,
) -> list[CoreCandidate]:
    candidates = [
        _core_candidate(row, hero_id, item_ids, eligible) for row in raw_candidates
    ]
    if not candidates or len(candidates) > CORE_CANDIDATE_LIMIT:
        raise ArtifactError(f"hero {hero_id} has no bounded supported core candidates")
    if len({candidate.item_ids for candidate in candidates}) != len(candidates):
        raise ArtifactError(f"hero {hero_id} has duplicate core candidates")
    expected = sorted(candidates, key=lambda row: (-row.joint_matches, row.item_ids))
    if candidates != expected:
        raise ArtifactError(f"hero {hero_id} core candidates are not deterministic")
    return candidates


def _validate_item_tier_coverage(items: tuple[ItemEvidence, ...], hero_id: int) -> None:
    for tier in range(1, 5):
        if not any(item.tier == tier for item in items):
            raise ArtifactError(f"hero {hero_id} has no Tier {tier} item evidence")


def _validate_policy_item_references(
    sequence_policy: SequencePolicy,
    situational_policy: SituationalPolicy,
    items: tuple[ItemEvidence, ...],
    hero_id: int,
) -> None:
    item_ids = {item.item_id for item in items}
    referenced_items = (
        set(sequence_policy.default_path)
        | {row.next_item_id for row in sequence_policy.transitions}
        | {branch.item_id for branch in situational_policy.branches}
        | {branch.comparator_item_id for branch in situational_policy.branches}
    )
    if not referenced_items <= item_ids:
        raise ArtifactError(f"hero {hero_id} policy references missing item evidence")
    items_by_id = {item.item_id: item for item in items}
    if any(
        items_by_id[branch.item_id].adopter_matches < MINIMUM_TIER_SUPPORT
        for branch in situational_policy.branches
    ):
        raise ArtifactError(f"hero {hero_id} has a weak situational tier item")


def _hero(value: object) -> HeroBuildEvidence:
    if not isinstance(value, dict):
        raise ArtifactError("build evidence contains a malformed hero")
    hero_id = _required_int(value.get("hero_id"), "hero id", minimum=1)
    name = value.get("hero")
    if not isinstance(name, str) or not name.strip():
        raise ArtifactError(f"hero {hero_id} has no name")
    eligible = _required_int(
        value.get("eligible_player_matches"), "eligible player matches", minimum=1
    )
    raw_items = value.get("items")
    raw_candidates = value.get("core_candidates")
    if not isinstance(raw_items, list) or not isinstance(raw_candidates, list):
        raise ArtifactError(f"hero {hero_id} has incomplete build evidence")
    items, item_ids = _hero_items(raw_items, hero_id, eligible)
    candidates = _core_candidates(raw_candidates, hero_id, item_ids, eligible)
    _validate_item_tier_coverage(items, hero_id)
    sequence_policy = _sequence_policy(value.get("sequence_policy"), hero_id)
    situational_policy = _situational_policy(value.get("situational_policy"), hero_id)
    _validate_policy_item_references(
        sequence_policy, situational_policy, items, hero_id
    )
    return HeroBuildEvidence(
        hero_id=hero_id,
        hero=name.strip(),
        eligible_player_matches=eligible,
        median_final_net_worth=_required_int(
            value.get("median_final_net_worth"), "median final net worth", minimum=1
        ),
        core_candidates=tuple(candidates),
        items=items,
        sequence_policy=sequence_policy,
        situational_policy=situational_policy,
    )


def _epoch(value: object, label: str) -> EpochBoundary:
    if not isinstance(value, dict):
        raise ArtifactError(f"build evidence lacks the {label} epoch")
    identity = value.get("identity")
    if not isinstance(identity, str):
        raise ArtifactError(f"build evidence has an invalid {label} epoch")
    return EpochBoundary(
        identity,
        _required_int(value.get("start_timestamp"), f"{label} epoch timestamp"),
    )


def load_build_evidence(path: Path) -> BuildEvidenceCatalog:
    try:
        raw = path.read_bytes()
        document = json.loads(raw)
    except (OSError, json.JSONDecodeError) as error:
        raise ArtifactError(f"could not read build evidence {path}: {error}") from error
    if not isinstance(document, dict):
        raise ArtifactError("build evidence root must be an object")
    artifact_id = document.get("artifact_id")
    payload = {key: value for key, value in document.items() if key != "artifact_id"}
    if not isinstance(artifact_id, str) or artifact_id != sha256_json(payload):
        raise ArtifactError("build evidence fingerprint does not match its contents")
    if document.get("schema_version") != BUILD_EVIDENCE_SCHEMA_VERSION:
        raise ArtifactError("unsupported build-evidence schema")
    method = document.get("method")
    expected_method = {
        "version": METHOD_VERSION,
        "core_item_count": CORE_ITEM_COUNT,
        "core_candidate_limit": CORE_CANDIDATE_LIMIT,
        "minimum_core_support": MINIMUM_CORE_SUPPORT,
        "minimum_tier_support": MINIMUM_TIER_SUPPORT,
        "tier_item_count": TIER_ITEM_COUNT,
    }
    if not isinstance(method, dict) or any(
        method.get(key) != value for key, value in expected_method.items()
    ):
        raise ArtifactError("build evidence uses an unsupported selection method")
    raw_heroes = document.get("heroes")
    requested = document.get("requested_hero_ids")
    patch = document.get("patch")
    cohort = document.get("cohort")
    epochs = document.get("epochs")
    if (
        not isinstance(raw_heroes, list)
        or not isinstance(requested, list)
        or not isinstance(patch, dict)
        or not isinstance(patch.get("identity"), str)
        or not isinstance(cohort, dict)
        or not isinstance(epochs, dict)
    ):
        raise ArtifactError("build evidence has an incomplete identity header")
    heroes = tuple(_hero(row) for row in raw_heroes)
    by_id = {hero.hero_id: hero for hero in heroes}
    if len(by_id) != len(heroes):
        raise ArtifactError("build evidence contains duplicate heroes")
    requested_ids = frozenset(
        _required_int(hero_id, "requested hero id", minimum=1) for hero_id in requested
    )
    if len(requested_ids) != len(requested):
        raise ArtifactError("build evidence contains duplicate requested heroes")
    if requested_ids != set(by_id):
        raise ArtifactError("build evidence does not exactly cover requested heroes")
    catalog = BuildEvidenceCatalog(
        artifact_id=artifact_id,
        client_version=_required_int(
            document.get("client_version"), "client version", minimum=1
        ),
        patch=patch,
        cohort=cohort,
        epochs=EpochSet(
            mechanics=_epoch(epochs.get("mechanics"), "mechanics"),
            matchmaking=_epoch(epochs.get("matchmaking"), "matchmaking"),
            map_objectives=_epoch(epochs.get("map_objectives"), "map objectives"),
            telemetry=_epoch(epochs.get("telemetry"), "telemetry"),
        ),
        rank_labels_sha256=_required_sha256(
            document.get("rank_labels_sha256"), "rank-label fingerprint"
        ),
        heroes_sha256=_required_sha256(
            document.get("heroes_sha256"), "hero fingerprint"
        ),
        items_sha256=_required_sha256(document.get("items_sha256"), "item fingerprint"),
        requested_hero_ids=requested_ids,
        heroes=by_id,
        raw_bytes=raw,
    )
    _required_sha256(catalog.patch.get("identity"), "patch fingerprint")
    _ = catalog.as_of_timestamp
    if catalog.as_of_timestamp < catalog.epochs.analysis_start_timestamp:
        raise ArtifactError("build evidence as-of cutoff precedes an epoch boundary")
    return catalog


def assert_build_evidence_compatible(
    catalog: BuildEvidenceCatalog,
    *,
    patch_identity: str,
    client_version: int,
    as_of_timestamp: int,
    match_mode: MatchMode,
    rank_range: RankRange,
    rank_catalog: RankCatalog,
    heroes: list[dict[str, Any]],
    assets: list[dict[str, Any]],
    epochs: EpochSet,
) -> None:
    cohort_mode = str(catalog.cohort.get("match_mode") or "").casefold()
    cohort_game = str(catalog.cohort.get("game_mode") or "").casefold()
    differences = []
    checks = {
        "patch": catalog.patch.get("identity") == patch_identity,
        "client_version": catalog.client_version == client_version,
        "as_of_timestamp": catalog.as_of_timestamp == as_of_timestamp,
        "match_mode": cohort_mode == match_mode.value,
        "game_mode": cohort_game == "normal",
        "minimum_badge": catalog.cohort.get("minimum_badge")
        == rank_range.minimum.badge_id,
        "maximum_badge": catalog.cohort.get("maximum_badge")
        == rank_range.maximum.badge_id,
        "rank_labels": catalog.rank_labels_sha256 == rank_catalog.sha256,
        "heroes": catalog.heroes_sha256 == sha256_json(heroes),
        "items": catalog.items_sha256 == sha256_json(assets),
        "epochs": catalog.epochs == epochs,
    }
    differences.extend(key for key, compatible in checks.items() if not compatible)
    if differences:
        raise ArtifactError(
            "build evidence is incompatible in: " + ", ".join(sorted(differences))
        )


def _replay_component_path(
    graph: ItemGraph,
    evidence_by_id: dict[int, ItemEvidence],
    path: tuple[int, ...],
) -> InventoryState:
    state = InventoryState()
    for item_id in path:
        if item_id not in evidence_by_id:
            raise MechanicsError(f"purchase path item {item_id} lacks evidence")
        missing = [
            component_id
            for component_id in graph.components[item_id]
            if component_id not in state.owned
        ]
        if missing:
            raise MechanicsError(
                f"purchase path item {item_id} precedes components {missing}"
            )
        state = purchase_item(graph, state, item_id)
    return state


def _expand_component_path(
    graph: ItemGraph,
    targets: tuple[int, ...],
    evidence_by_id: dict[int, ItemEvidence],
) -> tuple[int, ...]:
    priorities = {
        item_id: (
            item.median_valid_buy_net_worth
            if item.median_valid_buy_net_worth is not None
            else math.inf,
            item.median_buy_time_s,
            item_id,
        )
        for item_id, item in evidence_by_id.items()
    }
    return schedule_component_path(graph, targets, priorities)


def _select_core_candidate(
    graph: ItemGraph,
    evidence: HeroBuildEvidence,
    by_id: dict[int, ItemEvidence],
) -> tuple[CoreCandidate, tuple[int, ...], int]:
    for candidate in evidence.core_candidates:
        cost = sum(graph.require(item_id).cost for item_id in candidate.item_ids)
        if cost > evidence.median_final_net_worth:
            continue
        selected_order = tuple(
            sorted(
                candidate.item_ids,
                key=lambda item_id: (by_id[item_id].median_buy_time_s, item_id),
            )
        )
        purchase_order = tuple(
            sorted(
                candidate.item_ids,
                key=lambda item_id: (
                    by_id[item_id].median_valid_buy_net_worth
                    if by_id[item_id].median_valid_buy_net_worth is not None
                    else math.inf,
                    by_id[item_id].median_buy_time_s,
                    item_id,
                ),
            )
        )
        try:
            candidate_path = _expand_component_path(graph, purchase_order, by_id)
            state = _replay_component_path(graph, by_id, candidate_path)
        except MechanicsError:
            continue
        if len(candidate_path) != len(set(candidate_path)):
            continue
        if set(state.owned) == set(candidate.item_ids):
            return candidate, selected_order, cost
    raise ArtifactError(f"hero {evidence.hero_id} has no legal supported core")


def _validate_item_assets(
    evidence: HeroBuildEvidence,
    assets_by_id: dict[int, dict[str, Any]],
) -> None:
    for item in evidence.items:
        asset = assets_by_id.get(item.item_id)
        if (
            asset is None
            or str(asset.get("name") or "") != item.item
            or int(asset.get("item_tier") or 0) != item.tier
            or int(asset.get("cost") or 0) != item.cost
            or str(asset.get("item_slot_type") or "unknown").casefold() != item.slot
            or bool(asset.get("is_active_item")) != item.active
        ):
            raise ArtifactError(
                f"hero {evidence.hero_id} item {item.item_id} conflicts with assets"
            )


def _replay_selected_path(
    graph: ItemGraph,
    evidence: HeroBuildEvidence,
    by_id: dict[int, ItemEvidence],
    selected: CoreCandidate,
    selected_order: tuple[int, ...],
) -> tuple[int, ...]:
    path_ids = (
        evidence.sequence_policy.default_path
        if evidence.sequence_policy is not None
        else _expand_component_path(graph, selected_order, by_id)
    )
    if len(path_ids) != len(set(path_ids)):
        raise ArtifactError(
            f"hero {evidence.hero_id} component-expanded path repeats an item"
        )
    try:
        state = _replay_component_path(graph, by_id, path_ids)
    except MechanicsError as error:
        raise ArtifactError(
            f"hero {evidence.hero_id} has an invalid component-expanded path: {error}"
        ) from error
    if set(state.owned) == set(selected.item_ids):
        return path_ids
    fallback = _expand_component_path(graph, selected_order, by_id)
    if len(fallback) != len(set(fallback)):
        raise ArtifactError(
            f"hero {evidence.hero_id} component-expanded path repeats an item"
        )
    state = _replay_component_path(graph, by_id, fallback)
    if set(state.owned) != set(selected.item_ids):
        raise ArtifactError(
            f"hero {evidence.hero_id} component-expanded path does not end in CORE"
        )
    return fallback


def _tier_selection(
    evidence: HeroBuildEvidence,
    tier: int,
    core_ids: set[int],
    situational_ids: set[int],
) -> tuple[ItemEvidence, ...]:
    ranked = sorted(
        (
            item
            for item in evidence.items
            if item.tier == tier
            and item.item_id not in core_ids
            and item.adopter_matches >= MINIMUM_TIER_SUPPORT
        ),
        key=lambda item: (-item.adoption, -item.adopter_matches, item.item_id),
    )
    required = [item for item in ranked if item.item_id in situational_ids]
    if len(required) > TIER_ITEM_COUNT:
        raise ArtifactError(
            f"hero {evidence.hero_id} has too many Tier {tier} situational items"
        )
    membership = (
        required
        + [item for item in ranked if item.item_id not in situational_ids][
            : TIER_ITEM_COUNT - len(required)
        ]
    )
    if not membership:
        raise ArtifactError(
            f"hero {evidence.hero_id} lacks a supported non-CORE Tier {tier} item"
        )
    return tuple(
        sorted(
            membership,
            key=lambda item: (
                item.median_valid_buy_net_worth is None,
                item.median_valid_buy_net_worth
                if item.median_valid_buy_net_worth is not None
                else math.inf,
                item.median_buy_time_s,
                item.item_id,
            ),
        )
    )


def select_hero_build(
    evidence: HeroBuildEvidence,
    assets: list[dict[str, Any]],
) -> SelectedHeroBuild:
    graph = ItemGraph.from_assets(assets)
    assets_by_id = {
        int(asset["id"]): asset for asset in assets if isinstance(asset.get("id"), int)
    }
    by_id = {item.item_id: item for item in evidence.items}
    _validate_item_assets(evidence, assets_by_id)

    selected, selected_order, selected_cost = _select_core_candidate(
        graph, evidence, by_id
    )

    path_ids = _replay_selected_path(graph, evidence, by_id, selected, selected_order)

    tiers: dict[int, tuple[ItemEvidence, ...]] = {}
    core_ids = set(path_ids)
    situational_ids = {
        branch.item_id
        for branch in (
            evidence.situational_policy.branches if evidence.situational_policy else ()
        )
    }
    if situational_ids & core_ids:
        raise ArtifactError(
            f"hero {evidence.hero_id} situational items repeat the selected CORE"
        )
    for tier in range(1, 5):
        tiers[tier] = _tier_selection(evidence, tier, core_ids, situational_ids)
    return SelectedHeroBuild(
        hero_id=evidence.hero_id,
        core=tuple(by_id[item_id] for item_id in selected_order),
        core_purchase_path=tuple(by_id[item_id] for item_id in path_ids),
        tiers=tiers,
        core_joint_matches=selected.joint_matches,
        core_joint_share=selected.joint_matches / evidence.eligible_player_matches,
        median_final_net_worth=evidence.median_final_net_worth,
        core_target_cost=selected_cost,
    )


def evidence_record_sha256(catalog: BuildEvidenceCatalog) -> str:
    return hashlib.sha256(catalog.raw_bytes).hexdigest()
