"""Apply frozen core, order, mechanics, and pool gates to validation data."""

from scipy.stats import norm

from .discovery_data import HeroData
from .discovery_orders import core_times, order_evidence
from .discovery_quality import evaluate_core, rejection_reasons
from .discovery_types import Nomination


def admit_core(
    values: HeroData, row: Nomination, family: int, frozen_hash: str
) -> Nomination:
    validation = evaluate_core(values, tuple(row["items"]), "validation")
    limitations = [
        f"selection: {reason}" for reason in rejection_reasons(row["selection"])
    ]
    limitations.extend(
        f"validation: {reason}" for reason in rejection_reasons(validation, family)
    )
    reasons = list(row["selection_rejections"])
    adjusted = validation["adjusted"]
    validation["adjusted_lower_family"] = (
        adjusted["difference"]
        - float(norm.isf(0.025 / family)) * adjusted["standard_error"]
        if adjusted["difference"] is not None
        else None
    )
    ordered = order_evidence(
        core_times(values, row["items"], "validation"),
        row["items"],
        row["path"]["order"],
    )
    if not ordered["passes"]:
        limitations.append("validation: frozen order lacks support")
    if not row["path"]["admitted_before_validation"]:
        reasons.append("Frozen order lacks discovery or selection support")
    if not row["tactics"]["supported_focus"]:
        limitations.append(
            row["tactics"]["reason"] or "Mechanic text match is unavailable"
        )
    if not row["guide"]["ready"]:
        reasons.append(row["guide"]["reason"] or "Unsupported guide")
    return {
        **row,
        "evidence_status": "observed" if limitations else "outcome_supported",
        "evidence_limitations": limitations,
        "validation": validation,
        "order_validation": ordered,
        "hypotheses": family,
        "rejections": reasons,
        "frozen_sha256": frozen_hash,
    }


def discovery_record(row: Nomination) -> dict[str, object]:
    record = {
        key: value
        for key, value in row.items()
        if key not in {"guide", "automatic_choices", "branch_candidates"}
    }
    return {
        **record,
        "method": "eclat_leiden_pairwise",
        "frozen_guide": row["guide"],
        "test_evaluated": False,
    }
