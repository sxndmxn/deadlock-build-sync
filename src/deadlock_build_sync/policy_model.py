from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .policy_cards import (  # ruff: ignore[typing-only-first-party-import]
    CoreAlternativeCard,
    CounterCard,
)
from .policy_claims import EvidenceClaim, PolicyError
from .policy_graph import (
    NodeKind,
    PolicyNode,
)
from .snapshot import sha256_json


class AbstentionReason(StrEnum):
    STALE_MECHANICS = "stale_or_incomplete_mechanics"
    INADEQUATE_SUPPORT = "inadequate_support_or_overlap"
    EVIDENCE_CONFLICT = "evidence_conflict"
    ILLEGAL_PATH = "illegal_path"
    UNCLEAR_THREAT = "unclear_threat"
    OUT_OF_DISTRIBUTION = "out_of_distribution_state"
    TELEMETRY_FAILURE = "telemetry_failure"


@dataclass(frozen=True)
class Abstention:
    reason: AbstentionReason
    detail: str
    node_id: str | None = None

    def __post_init__(self) -> None:
        """Require an actionable abstention explanation.

        Raises:
            PolicyError: If no detail is supplied.

        """
        if not self.detail.strip():
            raise PolicyError("abstention detail must not be empty")


def _validate_counter_cards(
    cards: tuple[CounterCard, ...],
    nodes: tuple[PolicyNode, ...],
    claim_ids: list[str],
) -> None:
    item_ids = [card.item_id for card in cards]
    if len(item_ids) != len(set(item_ids)):
        raise PolicyError("counter cards must use distinct items")
    claims = set(claim_ids)
    actions = {
        (node.item_id, node.evidence_ref)
        for node in nodes
        if node.kind == NodeKind.PURCHASE and node.optional
    }
    for card in cards:
        if card.evidence_ref not in claims:
            raise PolicyError(
                f"counter card references missing evidence {card.evidence_ref}"
            )
        if (card.item_id, card.evidence_ref) not in actions:
            raise PolicyError("counter card has no matching optional purchase node")


def _validate_core_alternative_cards(
    cards: tuple[CoreAlternativeCard, ...],
    nodes: tuple[PolicyNode, ...],
    claim_ids: list[str],
) -> None:
    item_ids = [card.item_id for card in cards]
    if len(item_ids) != len(set(item_ids)):
        raise PolicyError("core alternative cards must use distinct items")
    claims = set(claim_ids)
    default_items = {
        node.item_id
        for node in nodes
        if node.kind == NodeKind.PURCHASE and not node.optional
    }
    for card in cards:
        if card.evidence_ref not in claims:
            raise PolicyError("core alternative card references missing evidence")
        if (
            card.item_id in default_items
            or card.comparator_item_id not in default_items
        ):
            raise PolicyError("core alternative card does not replace a default item")


@dataclass(frozen=True)
class BuildPolicy:
    schema_version: int
    hero_id: int
    variant: str
    invariant_kit_id: str
    strategic_role: str
    snapshot_id: str
    entry: str
    nodes: tuple[PolicyNode, ...]
    evidence: tuple[EvidenceClaim, ...]
    ability_plan: tuple[PolicyNode, ...] = ()
    abstentions: tuple[Abstention, ...] = ()
    counter_cards: tuple[CounterCard, ...] = ()
    core_alternatives: tuple[CoreAlternativeCard, ...] = ()
    path_id: str = "default"
    path_label: str = "Evidence Default"

    def __post_init__(self) -> None:
        """Validate policy-level identity and uniqueness.

        Raises:
            PolicyError: If identity fields or node/claim IDs are invalid.

        """
        if self.schema_version not in {1, 2, 3, 4, 5}:
            raise PolicyError(f"unsupported policy schema {self.schema_version}")
        if self.hero_id <= 0:
            raise PolicyError("policy hero id must be positive")
        if not all(
            value.strip()
            for value in (
                self.variant,
                self.invariant_kit_id,
                self.strategic_role,
                self.snapshot_id,
                self.entry,
                self.path_id,
                self.path_label,
            )
        ):
            raise PolicyError("policy identity fields must not be empty")
        graph_node_ids = [node.node_id for node in self.nodes]
        node_ids = [*graph_node_ids, *(node.node_id for node in self.ability_plan)]
        if len(set(node_ids)) != len(node_ids):
            raise PolicyError("policy node IDs must be unique")
        if any(node.kind != NodeKind.ABILITY for node in self.ability_plan):
            raise PolicyError("ability plan may contain only ability nodes")
        claim_ids = [claim.claim_id for claim in self.evidence]
        if len(set(claim_ids)) != len(claim_ids):
            raise PolicyError("policy evidence IDs must be unique")
        if self.entry not in set(graph_node_ids):
            raise PolicyError("policy entry does not resolve")
        for claim in self.evidence:
            if claim.snapshot_id != self.snapshot_id:
                raise PolicyError(f"claim {claim.claim_id} uses a stale snapshot")
        _validate_counter_cards(self.counter_cards, self.nodes, claim_ids)
        _validate_core_alternative_cards(self.core_alternatives, self.nodes, claim_ids)
        if self.schema_version == 1 and self.core_alternatives:
            raise PolicyError("policy schema 1 cannot contain core alternatives")

    @property
    def policy_id(self) -> str:
        return sha256_json(self.as_dict(include_policy_id=False))

    def as_dict(self, *, include_policy_id: bool = True) -> dict[str, object]:
        from .policy_codec import unstructure_build_policy

        return unstructure_build_policy(self, include_policy_id=include_policy_id)

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> BuildPolicy:
        """Decode a policy sidecar and verify its fingerprint.

        Returns:
            A fully typed policy graph.

        Raises:
            PolicyError: If structure, enums, identity, or fingerprint are invalid.

        """
        from .policy_codec import structure_build_policy

        return structure_build_policy(value)
