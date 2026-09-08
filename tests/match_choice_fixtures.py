"""Small branch records with explicit, corrected diagnostics."""

from copy import deepcopy
from statistics import NormalDist


def make_branch_document(
    *, item: int = 7, condition: str = "relative_wealth", value: str | int = "behind"
) -> dict[str, object]:
    lower = 0.1 - 0.02 / 1.96 * NormalDist().inv_cdf(0.975)
    fold = {
        "support": 40,
        "comparison_support": 40,
        "effective_support": 80,
        "overlap": 1.0,
        "maximum_weight": 2.0,
        "maximum_standardized_mean_difference": 0.0,
        "estimate": 0.10,
        "interval": [0.08, 0.12],
    }
    evidence = {
        "hypotheses": 1,
        "lower_bound": lower,
        "test_evaluated": False,
        "admitted": True,
        "stable": True,
        "failed_gates": [],
        "fold_diagnostics": {"train": deepcopy(fold), "validation": deepcopy(fold)},
        "gates": dict.fromkeys(
            (
                "support",
                "overlap",
                "balance",
                "uncertainty",
                "temporal_stability",
                "corrected_outcome",
                "legal_path",
                "pre_decision_cohort",
            ),
            True,
        ),
    }
    return {
        "version": 1,
        "test_evaluated": False,
        "branches": [
            {
                "item_id": item,
                "after_step": 2,
                "comparator_item_id": 2,
                "condition": condition,
                "value": value,
                "support": 80,
                "lower_bound": lower,
                "evidence": evidence,
            }
        ],
    }
