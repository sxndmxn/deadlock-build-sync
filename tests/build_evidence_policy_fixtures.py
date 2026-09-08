"""Fresh core alternative and situational branch records."""


def core_alternative() -> dict[str, object]:
    return {
        "item_id": 303,
        "comparator_item_id": 302,
        "stage": 6,
        "support": 40,
        "comparison_support": 50,
        "effective_support": 30.0,
        "overlap": 0.8,
        "stable": True,
        "dr_estimate": 0.03,
        "comparative_interval": [0.01, 0.05],
        "vs": "Heavy Spirit damage",
        "why": "Spirit Resist",
        "swap": "Replaces Tier 3 Item 2",
        "when": "Before the next Spirit-heavy fight",
        "skip": "Keep default when control matters more",
        "mechanics_refs": ["asset:item:303:description"],
        "comparator_mechanics_refs": ["asset:item:302:description"],
        "fold_estimates": {
            "train": 0.03,
            "validation": 0.04,
            "test": -0.03,
        },
        "fold_diagnostics": {
            fold: {
                "support": 40,
                "comparison_support": 50,
                "effective_support": 30.0,
                "overlap": 0.8,
                "maximum_standardized_mean_difference": 0.05,
                "estimate": estimate,
                "interval": [0.01, 0.05],
            }
            for fold, estimate in (("train", 0.03), ("validation", 0.04))
        },
    }


def situational_branch() -> dict[str, object]:
    return {
        "threat": "healing",
        "item_id": 103,
        "enemy_hero_id": 7,
        "enemy_scope": "whole_enemy_team",
        "phase": 1,
        "tier": 1,
        "mechanic_ref": "item/103/healing-reduction",
        "enemy_mechanics_refs": ["asset:ability:7:description"],
        "comparator": "same-tier default continuation or save",
        "comparator_item_id": 101,
        "comparison_support": 20,
        "same_opportunity": True,
        "support": 20,
        "effective_support": 20.0,
        "overlap": 0.5,
        "stable": True,
        "comparative_interval": [0.01, 0.06],
        "fold_comparative_estimates": {
            "train": 0.03,
            "validation": 0.04,
            "test": 0.02,
        },
        "fold_support": {
            "train": {"item": 20, "comparator": 20},
            "validation": {"item": 20, "comparator": 20},
            "test": {"item": 20, "comparator": 20},
        },
        "trigger": "Enemy healing is observed.",
        "replacement": "Replace the next optional purchase.",
        "execution": "Apply healing reduction after contact.",
        "failure_condition": "Skip when healing is not material.",
    }
