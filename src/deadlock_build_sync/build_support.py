"""Shared support limits and separate observational outcome requirements."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .artifacts import ArtifactError
from .build_evidence_values import _required_int
from .value_validation import object_dict

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True)
class SupportPolicy:
    core_owners: int = 100
    order_followers: int = 20
    order_share: float = 0.10
    pool_buyers: int = 20
    pool_limit: int = 10

    def core_reasons(self, discovery: int, selection: int) -> list[str]:
        return [
            f"fewer than {self.core_owners} {fold} core owners"
            for fold, count in (("discovery", discovery), ("selection", selection))
            if count < self.core_owners
        ]

    def order_supported(self, owners: int, followers: int) -> bool:
        return (
            self.core_owners <= owners
            and self.order_followers <= followers <= owners
            and followers / owners >= self.order_share
        )


SUPPORT = SupportPolicy()


def numeric(row: Mapping[str, object], key: str) -> float:
    value = row.get(key)
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ArtifactError(f"Discovery has invalid {key}")
    return float(value)


@dataclass(frozen=True)
class OutcomeEvidence:
    owners: int
    win_rate: float | None
    win_lower: float
    win_p: float
    lift: float
    overlap: int
    overlap_share: float
    adjusted_lower: float | None
    adjusted_p: float

    @classmethod
    def parse(cls, row: Mapping[str, object]) -> OutcomeEvidence:
        owners = _required_int(row.get("owners"), "core owners")
        wins = _required_int(row.get("wins"), "core wins")
        adjusted = object_dict(row.get("adjusted"))
        if adjusted is None or wins > owners:
            raise ArtifactError("Discovery has inconsistent core outcomes")
        rate = numeric(row, "win_rate") if owners else None
        if (owners and not math.isclose(rate or 0, wins / owners)) or (
            not owners and row.get("win_rate") is not None
        ):
            raise ArtifactError("Discovery has inconsistent core win rate")
        overlap = _required_int(adjusted.get("core_overlap"), "comparable core owners")
        share = numeric(adjusted, "overlap_share")
        if overlap > owners or not math.isclose(share, overlap / max(1, owners)):
            raise ArtifactError("Discovery has inconsistent comparable-state overlap")
        lower = (
            numeric(adjusted, "lower_95")
            if adjusted.get("difference") is not None
            else None
        )
        if lower is None and adjusted.get("lower_95") is not None:
            raise ArtifactError("Discovery has an estimate without a contrast")
        if lower is not None:
            numeric(adjusted, "difference")
            if numeric(adjusted, "standard_error") < 0:
                raise ArtifactError("Discovery has negative uncertainty")
        result = cls(
            owners,
            rate,
            numeric(row, "win_lower_95"),
            numeric(row, "win_p_greater_half"),
            numeric(row, "joint_lift"),
            overlap,
            share,
            lower,
            numeric(adjusted, "p_greater"),
        )
        if (
            not all(
                0 <= value <= 1
                for value in (result.win_p, result.adjusted_p, result.win_lower)
            )
            or result.lift < 0
        ):
            raise ArtifactError("Discovery has invalid outcome probabilities")
        return result


def outcome_limitations(
    row: Mapping[str, object] | OutcomeEvidence, hypotheses: int | None = None
) -> list[str]:
    evidence = row if isinstance(row, OutcomeEvidence) else OutcomeEvidence.parse(row)
    reasons = []
    if evidence.owners < SUPPORT.core_owners:
        reasons.append("fewer than 100 core owners")
    if evidence.win_rate is None or evidence.win_rate < 0.52:
        reasons.append("observed win rate below 52%")
    if evidence.lift < 1.1:
        reasons.append("joint ownership lift below 1.1")
    if evidence.overlap < SUPPORT.core_owners or evidence.overlap_share < 0.8:
        reasons.append("insufficient comparable-state overlap")
    if hypotheses is None:
        if evidence.win_lower <= 0.5:
            reasons.append("win lower bound does not exceed 50%")
        if evidence.adjusted_lower is None or evidence.adjusted_lower <= 0:
            reasons.append("adjusted lower bound does not exceed zero")
    else:
        threshold = 0.025 / max(1, hypotheses)
        if evidence.win_p > threshold:
            reasons.append("win evidence fails family correction")
        if evidence.adjusted_lower is None or evidence.adjusted_p > threshold:
            reasons.append("adjusted evidence fails family correction")
    return reasons
