from __future__ import annotations

from dataclasses import dataclass

from .mechanics import (
    BASE_INVENTORY_SLOTS,
)
from .policy_claims import ClaimClass, PolicyError


@dataclass(frozen=True)
class CounterCard:
    threat: str
    item_id: int
    comparator_item_id: int
    mechanic_ref: str
    legal_timing: str
    alternative: str
    replacement: str
    execution_mode: str
    failure_condition: str
    evidence_ref: str
    enemy_hero_id: int | None = None
    enemy_scope: str = "whole_enemy_team"
    phase: int = 0
    tier: int = 1
    enemy_mechanics_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Require the complete mechanics-first counter contract.

        Raises:
            PolicyError: If any counter decision field is empty or invalid.

        """
        values = (
            self.threat,
            self.mechanic_ref,
            self.legal_timing,
            self.alternative,
            self.replacement,
            self.execution_mode,
            self.failure_condition,
            self.evidence_ref,
        )
        if (
            self.item_id <= 0
            or self.comparator_item_id <= 0
            or self.comparator_item_id == self.item_id
            or not all(value.strip() for value in values)
        ):
            raise PolicyError(
                "counter card is missing a mechanics-first contract field"
            )
        if self.enemy_hero_id is not None and self.enemy_hero_id <= 0:
            raise PolicyError("counter card enemy hero id must be positive")
        if (
            self.enemy_scope not in {"same_lane", "whole_enemy_team"}
            or not 0 <= self.phase <= 3
            or not 1 <= self.tier <= 4
            or not self.enemy_mechanics_refs
        ):
            raise PolicyError("counter card has invalid enemy-state evidence")

    def as_dict(self) -> dict[str, object]:
        """Return the complete serializable decision contract.

        Returns:
            A JSON-compatible counter-card object.

        """
        from .policy_codec import unstructure_counter_card

        return unstructure_counter_card(self)

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> CounterCard:
        """Decode a complete counter card.

        Returns:
            The validated counter card.

        Raises:
            PolicyError: If the object is incomplete or malformed.

        """
        from .policy_codec import structure_counter_card

        return structure_counter_card(value)


@dataclass(frozen=True)
class CoreAlternativeCard:
    item_id: int
    comparator_item_id: int
    stage: int
    vs: str
    why: str
    swap: str
    when: str
    skip: str
    mechanics_refs: tuple[str, ...]
    comparator_mechanics_refs: tuple[str, ...]
    evidence_ref: str
    support: int
    effective_support: float
    overlap: float
    interval: tuple[float, float]
    fold_estimates: dict[str, float]

    def __post_init__(self) -> None:
        """Require an estimable, mechanics-grounded CORE substitution card.

        Raises:
            PolicyError: If the card fails its identity or evidence contract.

        """
        text = (
            self.vs,
            self.why,
            self.swap,
            self.when,
            self.skip,
            self.evidence_ref,
        )
        identity_invalid = (
            self.item_id <= 0
            or self.comparator_item_id <= 0
            or self.item_id == self.comparator_item_id
            or not 1 <= self.stage <= BASE_INVENTORY_SLOTS
        )
        evidence_invalid = (
            self.support < 20
            or self.effective_support < 20
            or not 0.5 <= self.overlap <= 1
        )
        interval_invalid = (
            self.interval[0] <= 0
            or self.interval[0] > self.interval[1]
            or self.interval[1] - self.interval[0] > 0.10
        )
        content_invalid = (
            not all(value.strip() for value in text)
            or not self.mechanics_refs
            or not self.comparator_mechanics_refs
        )
        folds_invalid = (
            not {"train", "validation"} <= set(self.fold_estimates)
            or abs(
                self.fold_estimates.get("train", 0.0)
                - self.fold_estimates.get("validation", 0.0)
            )
            > 0.05
        )
        if any((
            identity_invalid,
            evidence_invalid,
            interval_invalid,
            content_invalid,
            folds_invalid,
        )):
            raise PolicyError("core alternative card is incomplete or unsupported")


@dataclass(frozen=True)
class SpikeCard:
    name: str
    prerequisites: tuple[str, ...]
    acquisition_state: str
    mechanical_delta: str
    conversion_window: str
    failure_conditions: tuple[str, ...]
    counterplay: tuple[str, ...]
    evidence_class: ClaimClass
    confidence: float
    evidence_ref: str

    def __post_init__(self) -> None:
        """Require a state transition rather than an outcome-only peak.

        Raises:
            PolicyError: If transition evidence or confidence is missing.

        """
        if not 0 <= self.confidence <= 1:
            raise PolicyError("spike confidence must be between zero and one")
        if self.evidence_class == ClaimClass.DESCRIPTIVE and not self.mechanical_delta:
            raise PolicyError("an outcome-only maximum cannot define a power spike")
        if not (
            self.name.strip()
            and self.prerequisites
            and self.acquisition_state.strip()
            and self.mechanical_delta.strip()
            and self.conversion_window.strip()
            and self.failure_conditions
            and self.counterplay
            and self.evidence_ref.strip()
        ):
            raise PolicyError("spike card is missing a state-transition field")
