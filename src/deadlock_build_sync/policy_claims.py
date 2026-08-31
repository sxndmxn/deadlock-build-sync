from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .snapshot import EvidenceUnit  # ruff: ignore[typing-only-first-party-import]


class PolicyError(ValueError):
    """Raised when a build policy is incomplete, ambiguous, stale, or illegal."""


class ClaimClass(StrEnum):
    MECHANICAL = "mechanical"
    DESCRIPTIVE = "descriptive"
    PREDICTIVE = "predictive"
    CAUSAL = "causal"


_LANGUAGE_CEILINGS = {
    ClaimClass.MECHANICAL: frozenset({"grants", "scales", "requires", "can target"}),
    ClaimClass.DESCRIPTIVE: frozenset({
        "observed",
        "associated",
        "adopted",
        "rate",
        "more common",
    }),
    ClaimClass.PREDICTIVE: frozenset({
        "predicts",
        "estimated",
        "conditional",
        "expected",
    }),
    ClaimClass.CAUSAL: frozenset({"causes", "improves", "reduces", "effect"}),
}
_CAUSAL_PHRASES = (
    "causes",
    "adds win rate",
    "improves win rate",
    "increases your chance",
    "item impact",
    "guarantees",
)


@dataclass(frozen=True)
class EvidenceClaim:
    claim_id: str
    claim_class: ClaimClass
    snapshot_id: str
    cohort: dict[str, object]
    unit: EvidenceUnit
    support: int
    mechanics_refs: tuple[str, ...]
    language_ceiling: frozenset[str]
    numerator: int | None = None
    denominator: int | None = None
    estimate: float | None = None
    interval: tuple[float, float] | None = None
    comparison_baseline: float | None = None

    def __post_init__(self) -> None:
        """Validate claim identity, support, and language strength.

        Raises:
            PolicyError: If required evidence metadata is missing or inconsistent.

        """
        if not self.claim_id.strip() or not self.snapshot_id.strip():
            raise PolicyError("evidence claim identity must not be empty")
        if not self.cohort:
            raise PolicyError(f"claim {self.claim_id} has no cohort")
        if self.support < 0:
            raise PolicyError(f"claim {self.claim_id} has negative support")
        if not self.language_ceiling <= _LANGUAGE_CEILINGS[self.claim_class]:
            raise PolicyError(f"claim {self.claim_id} exceeds its language ceiling")
        if self.claim_class == ClaimClass.MECHANICAL and not self.mechanics_refs:
            raise PolicyError(f"mechanical claim {self.claim_id} has no mechanics refs")
        quantitative = self.estimate is not None or self.interval is not None
        if quantitative and self.support == 0:
            raise PolicyError(f"quantitative claim {self.claim_id} has no support")
        if self.interval is not None:
            lower, upper = self.interval
            if lower > upper:
                raise PolicyError(f"claim {self.claim_id} has an inverted interval")
        if self.denominator is not None and self.denominator != self.support:
            raise PolicyError(f"claim {self.claim_id} denominator differs from support")

    def as_dict(self) -> dict[str, object]:
        from .policy_codec import unstructure_evidence_claim

        return unstructure_evidence_claim(self)

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> EvidenceClaim:
        """Decode and validate one evidence object.

        Returns:
            A typed claim.

        Raises:
            PolicyError: If enum values or quantitative fields are malformed.

        """
        from .policy_codec import structure_evidence_claim

        return structure_evidence_claim(value)

    def validate_sentence(self, sentence: str) -> None:
        """Enforce the deterministic prose ceiling for this claim.

        Raises:
            PolicyError: If non-causal evidence is phrased as causal impact.

        """
        normalized = sentence.casefold()
        if self.claim_class != ClaimClass.CAUSAL and any(
            phrase in normalized for phrase in _CAUSAL_PHRASES
        ):
            raise PolicyError(
                f"sentence exceeds {self.claim_class.value} claim {self.claim_id}"
            )
