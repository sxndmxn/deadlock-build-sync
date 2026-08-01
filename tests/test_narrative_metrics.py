from __future__ import annotations

import copy
import json
from typing import Any

import pytest
from deepeval.test_case import LLMTestCase

from evals import metrics
from scripts import generate_narratives


@pytest.fixture
def hero() -> dict[str, Any]:
    return {
        "hero_id": 12,
        "hero": "Kelvin",
        "abilities": [
            {
                "ability": f"Ability {quarter}",
                "description": {
                    "desc": (
                        "Creates repeated area control, protects allies, and grants "
                        "movement speed around an objective."
                    )
                },
            }
            for quarter in metrics.QUARTERS
        ],
        "ability_path": {
            "raw_win_rate": 0.58,
            "matches": 120,
            "steps": [
                {
                    "quarter": index,
                    "ability": f"Ability {quarter}",
                    "upgrade": "UNLOCK",
                }
                for index, quarter in enumerate(metrics.QUARTERS, start=1)
            ],
        },
        "tiers": {
            quarter: [
                {
                    "rank_by_pick_rate": 1,
                    "item": f"Item {quarter}",
                    "description": {
                        "desc": (
                            "Reduces cooldowns for repeated control and grants a "
                            "protective movement-speed effect."
                        )
                    },
                    "raw_win_rate": 0.55 + (index * 0.01),
                    "matches": 1000 - (index * 100),
                }
            ]
            for index, quarter in enumerate(metrics.QUARTERS)
        },
        "duration_curve": {
            "shape": "LATE_SCALING",
            "strongest_phase": "LATE (45m+)",
            "weakest_phase": "EARLY (<30m)",
            "phases": [
                {
                    "label": "EARLY (<30m)",
                    "raw_win_rate": 0.50,
                    "matches": 500,
                },
                {
                    "label": "MID (30–45m)",
                    "raw_win_rate": 0.55,
                    "matches": 800,
                },
                {
                    "label": "LATE (45m+)",
                    "raw_win_rate": 0.60,
                    "matches": 300,
                },
            ],
        },
    }


@pytest.fixture
def response() -> dict[str, Any]:
    return {
        "tactical_profile": {
            "power_spikes": [
                {
                    "quarter": "III",
                    "trigger": "Item III with Ability III UNLOCK",
                    "tactical_unlock": (
                        "Repeated casts and area control permit coordinated "
                        "objective pressure."
                    ),
                }
            ],
            "duration_plan": {
                "shape": "LATE_SCALING",
                "strongest_phase": "LATE (45m+)",
                "weakest_phase": "EARLY (<30m)",
                "macro_plan": (
                    "Scale patiently, convert clean objectives, and close whenever "
                    "the team earns an ending opportunity."
                ),
                "late_build_response": "REINFORCE",
                "response_reason": (
                    "The late package reinforces repeated control and protection."
                ),
            },
        },
        "quarters": {
            "I": (
                "TIER I: Hold lane with Item I and use Ability I when an enemy "
                "commits, then disengage to a safe position."
            ),
            "II": (
                "TIER II: Rotate and group with Item II; use Ability II after an "
                "exposed target commits to accelerate the fight."
            ),
            "III": (
                "TIER III: Preserve farm while scaling with Item III, then use "
                "Ability III when the team can pressure an objective safely."
            ),
            "IV": (
                "TIER IV: Group to close the game with Item IV; use Ability IV "
                "after the priority target commits, then convert the objective."
            ),
        },
    }


def _test_case(output: object) -> LLMTestCase:
    return LLMTestCase(input="prompt", actual_output=json.dumps(output))


def test_per_tier_metric_checks_every_quarter(
    hero: dict[str, Any],
    response: dict[str, Any],
) -> None:
    metric = metrics.PerTierTacticalQualityMetric(hero)

    score = metric.measure(_test_case(response))

    assert score == 1.0
    assert metric.is_successful()


def test_per_tier_metric_rejects_future_items(
    hero: dict[str, Any],
    response: dict[str, Any],
) -> None:
    invalid = copy.deepcopy(response)
    invalid["quarters"]["I"] += " Save Item IV for the exposed target."
    metric = metrics.PerTierTacticalQualityMetric(hero)

    score = metric.measure(_test_case(invalid))

    assert score == 0.0
    assert not metric.is_successful()
    assert "future item(s): Item IV" in str(metric.reason)


def test_per_tier_metric_recognizes_team_relative_positioning(
    hero: dict[str, Any],
    response: dict[str, Any],
) -> None:
    response["quarters"]["II"] = (
        "TIER II: Accelerate into grouped skirmishes with Item II after Ability II "
        "unlocks, then beam slowed enemies while staying near your team."
    )
    metric = metrics.PerTierTacticalQualityMetric(hero)

    score = metric.measure(_test_case(response))

    assert score == 1.0
    assert metric.is_successful()


def test_per_tier_metric_recognizes_grouped_positioning(
    hero: dict[str, Any],
    response: dict[str, Any],
) -> None:
    response["quarters"]["III"] = (
        "TIER III: Preserve farm with Item III and Ability III UNLOCK, then group "
        "and force an objective when the full control cycle is ready."
    )
    metric = metrics.PerTierTacticalQualityMetric(hero)

    score = metric.measure(_test_case(response))

    assert score == 1.0


def test_cross_tier_metric_requires_distinct_progression(
    hero: dict[str, Any],
    response: dict[str, Any],
) -> None:
    metric = metrics.CrossTierProgressionMetric(hero)

    score = metric.measure(_test_case(response))

    assert score == 1.0
    assert metric.is_successful()


def test_macro_features_recognize_rotations_without_treating_land_as_lane() -> None:
    features = metrics._macro_features(  # ruff: ignore[private-member-access]
        "Use purposeful rotations, then land Frost Grenade on the target."
    )

    assert "roam" in features
    assert "lane" not in features


def test_macro_identity_ignores_wording_but_preserves_strategy(
    hero: dict[str, Any],
) -> None:
    first = metrics._macro_stage_identity(  # ruff: ignore[private-member-access]
        "Preserve economy between coordinated objective attempts.",
        "III",
        hero,
    )
    paraphrase = metrics._macro_stage_identity(  # ruff: ignore[private-member-access]
        "Farm safely, then group to pressure an objective.",
        "III",
        hero,
    )
    contradictory = metrics._macro_stage_identity(  # ruff: ignore[private-member-access]
        "Force every objective fight when allies group.",
        "III",
        hero,
    )

    assert first == paraphrase == "scale_and_convert"
    assert contradictory == "force_without_economy"


def test_pairwise_quarter_stability_accepts_majority_without_global_intersection() -> (
    None
):
    sets_by_quarter = {
        "II": [
            {"Frost Grenade", "Arctic Beam", "Frozen Shelter"},
            {"Frozen Shelter"},
            {"Frost Grenade", "Arctic Beam"},
        ]
    }

    score = metrics._pairwise_quarter_containment(  # ruff: ignore[private-member-access]
        sets_by_quarter
    )

    assert score == pytest.approx(2 / 3)


def test_majority_quarter_support_accepts_shared_core_with_different_extras() -> None:
    sets_by_quarter = {
        "III": [
            {"Rapid Recharge", "Superior Cooldown"},
            {"Rapid Recharge"},
            {"Rapid Recharge", "Greater Expansion"},
        ]
    }

    score = metrics._majority_quarter_support(  # ruff: ignore[private-member-access]
        sets_by_quarter
    )

    assert score == 1.0


def test_majority_quarter_support_rejects_outlier_plan() -> None:
    sets_by_quarter = {
        "III": [
            {"Rapid Recharge"},
            {"Rapid Recharge"},
            {"Greater Expansion"},
        ]
    }

    score = metrics._majority_quarter_support(  # ruff: ignore[private-member-access]
        sets_by_quarter
    )

    assert score == pytest.approx(2 / 3)


def test_majority_stability_preserves_shared_core_permissions() -> None:
    shared = {
        "objective_force",
        "pressure_close",
        "survivability",
        "sustain",
        "teamfight_control",
    }
    feature_sets = [
        shared | {"disengage_reset", "mobility_access"},
        shared | {"counter_engage", "repeatable_uptime"},
        shared | {"counter_engage", "repeatable_uptime"},
    ]

    score = metrics._majority_containment(  # ruff: ignore[private-member-access]
        feature_sets
    )

    assert score == pytest.approx(19 / 21)


def test_ability_mentions_accept_unique_capitalized_shorthand() -> None:
    names = ["Frost Grenade", "Arctic Beam", "Ice Path", "Frozen Shelter"]

    mentions = metrics._mentioned_ability_names(  # ruff: ignore[private-member-access]
        "Exit Shelter into Grenade and Beam control.", names
    )
    lowercase = metrics._mentioned_ability_names(  # ruff: ignore[private-member-access]
        "Follow the safest path to shelter.", names
    )

    assert mentions == {"Frost Grenade", "Arctic Beam", "Frozen Shelter"}
    assert lowercase == set()


def test_grounding_recognizes_spirit_control_as_scaling_support() -> None:
    item = {
        "item": "Boundless Spirit",
        "stats": [{"label": "Spirit Power"}],
    }
    ability = {
        "ability": "Ice Path",
        "description": {
            "desc": "Creates a movement path.",
            "t3_desc": "Grants Spirit while on Ice Path.",
        },
    }

    violations = metrics._mechanic_grounding_violations(  # ruff: ignore[private-member-access]
        item,
        ability,
        "T3",
        "Boundless Spirit with Ice Path T3",
        (
            "Ice Path carries its final Spirit enhancement, enabling a stronger "
            "spirit-control entry."
        ),
    )

    assert violations == []


def test_grounding_rejects_charge_item_for_non_charge_ability() -> None:
    item = {
        "item": "Rapid Recharge",
        "stats": [
            {"label": "Bonus Ability Charges"},
            {"label": "Cooldown Reduction For Charged Abilities"},
        ],
    }
    ability = {
        "ability": "Arctic Beam",
        "description": {"t3_desc": "Reduces cooldown and adds nearby beams."},
        "stats": [
            {
                "property": "AbilityCooldownBetweenCharge",
                "label": "Charge Delay",
                "value": "-1.0",
            }
        ],
    }

    violations = metrics._mechanic_grounding_violations(  # ruff: ignore[private-member-access]
        item,
        ability,
        "T3",
        "Rapid Recharge with Arctic Beam T3",
        (
            "Rapid Recharge adds charges while Arctic Beam T3 reduces cooldown, "
            "permitting repeated control."
        ),
    )

    assert "charge-specific item does not support the selected ability" in violations

    ability["stats"] = [
        {"property": "AbilityCharges", "label": "Charges", "value": "2"}
    ]
    charged_violations = metrics._mechanic_grounding_violations(  # ruff: ignore[private-member-access]
        item,
        ability,
        "T3",
        "Rapid Recharge with Arctic Beam T3",
        (
            "Rapid Recharge adds charges while Arctic Beam T3 reduces cooldown, "
            "permitting repeated control."
        ),
    )

    assert "charge-specific item does not support the selected ability" not in (
        charged_violations
    )


def test_grounding_does_not_treat_charges_up_as_ability_charges() -> None:
    item = {
        "item": "Quicksilver Reload",
        "description": {
            "desc": "The imbued ability charges up over time with bonus damage."
        },
    }
    ability = {
        "ability": "Full Auto",
        "description": {"t3_desc": "Adds spirit damage to every bullet."},
        "stats": [],
    }

    violations = metrics._mechanic_grounding_violations(  # ruff: ignore[private-member-access]
        item,
        ability,
        "T3",
        "Quicksilver Reload with Full Auto T3",
        (
            "Quicksilver Reload adds damage while Full Auto T3 adds spirit damage, "
            "permitting a stronger committed attack."
        ),
    )

    assert (
        "charge-specific item does not support the selected ability" not in violations
    )


def test_repeated_metric_passes_stable_outputs(
    monkeypatch: pytest.MonkeyPatch,
    hero: dict[str, Any],
    response: dict[str, Any],
) -> None:
    monkeypatch.setattr(
        generate_narratives,
        "validate_response",
        lambda *_args, **_kwargs: {},
    )
    samples = [
        {
            "attempt": attempt,
            "duration_seconds": 30 + attempt,
            "output": response,
        }
        for attempt in range(1, 4)
    ]
    metric = metrics.RepeatedGenerationStabilityMetric(hero)

    score = metric.measure(_test_case(samples))

    assert score == 1.0
    assert metric.is_successful()
    assert metric.score_breakdown["macro_plan_stability"] == 1.0


def test_repeated_metric_accepts_adjacent_tactically_equivalent_spikes(
    monkeypatch: pytest.MonkeyPatch,
    hero: dict[str, Any],
    response: dict[str, Any],
) -> None:
    monkeypatch.setattr(
        generate_narratives,
        "validate_response",
        lambda *_args, **_kwargs: {},
    )
    adjacent = copy.deepcopy(response)
    adjacent["tactical_profile"]["power_spikes"] = [
        {
            "quarter": "II",
            "trigger": "Item II with Ability II UNLOCK",
            "tactical_unlock": (
                "Repeated casts and area control permit coordinated objective pressure."
            ),
        }
    ]
    samples = [
        {"attempt": 1, "duration_seconds": 31, "output": response},
        {"attempt": 2, "duration_seconds": 32, "output": response},
        {"attempt": 3, "duration_seconds": 33, "output": adjacent},
    ]
    metric = metrics.RepeatedGenerationStabilityMetric(hero)

    score = metric.measure(_test_case(samples))

    assert score >= metric.threshold
    assert metric.is_successful()
    assert metric.score_breakdown["power_spike_timing_stability"] >= 0.9
    assert metric.score_breakdown["power_spike_tactical_stability"] == 1.0
    assert metric.score_breakdown["power_spike_exact_identity"] < 1.0


def test_repeated_metric_rejects_wrong_tier_power_spike_trigger(
    monkeypatch: pytest.MonkeyPatch,
    hero: dict[str, Any],
    response: dict[str, Any],
) -> None:
    monkeypatch.setattr(
        generate_narratives,
        "validate_response",
        lambda *_args, **_kwargs: {},
    )
    drifted = copy.deepcopy(response)
    drifted["tactical_profile"]["power_spikes"][0]["trigger"] = (
        "Item IV with Ability IV UNLOCK"
    )
    samples = [
        {"attempt": 1, "duration_seconds": 31, "output": response},
        {"attempt": 2, "duration_seconds": 32, "output": response},
        {"attempt": 3, "duration_seconds": 33, "output": drifted},
    ]
    metric = metrics.RepeatedGenerationStabilityMetric(hero)

    score = metric.measure(_test_case(samples))

    assert score < metric.threshold
    assert not metric.is_successful()
    assert metric.score_breakdown["power_spike_grounding"] < 1.0


def test_repeated_metric_rejects_unsupported_power_spike_mechanics(
    monkeypatch: pytest.MonkeyPatch,
    hero: dict[str, Any],
    response: dict[str, Any],
) -> None:
    monkeypatch.setattr(
        generate_narratives,
        "validate_response",
        lambda *_args, **_kwargs: {},
    )
    invented = copy.deepcopy(response)
    invented["tactical_profile"]["power_spikes"][0]["tactical_unlock"] = (
        "The combination grants invisibility and a disarm, permitting an "
        "unsupported solo assassination."
    )
    samples = [
        {"attempt": attempt, "duration_seconds": 30 + attempt, "output": invented}
        for attempt in range(1, 4)
    ]
    metric = metrics.RepeatedGenerationStabilityMetric(hero)

    score = metric.measure(_test_case(samples))

    assert score < metric.threshold
    assert not metric.is_successful()
    assert metric.score_breakdown["power_spike_grounding"] == 0.0


def test_repeated_metric_rejects_early_late_spike_contradiction(
    monkeypatch: pytest.MonkeyPatch,
    hero: dict[str, Any],
    response: dict[str, Any],
) -> None:
    monkeypatch.setattr(
        generate_narratives,
        "validate_response",
        lambda *_args, **_kwargs: {},
    )
    early = copy.deepcopy(response)
    early["tactical_profile"]["power_spikes"] = [
        {
            "quarter": "I",
            "trigger": "Item I with Ability I UNLOCK",
            "tactical_unlock": (
                "Repeated casts and area control permit coordinated objective pressure."
            ),
        }
    ]
    late = copy.deepcopy(response)
    late["tactical_profile"]["power_spikes"] = [
        {
            "quarter": "IV",
            "trigger": "Item IV with Ability IV UNLOCK",
            "tactical_unlock": (
                "Repeated casts and area control permit coordinated objective pressure."
            ),
        }
    ]
    samples = [
        {"attempt": 1, "duration_seconds": 31, "output": early},
        {"attempt": 2, "duration_seconds": 32, "output": late},
        {"attempt": 3, "duration_seconds": 33, "output": early},
    ]
    metric = metrics.RepeatedGenerationStabilityMetric(hero)

    score = metric.measure(_test_case(samples))

    assert score < metric.threshold
    assert not metric.is_successful()
    assert metric.score_breakdown["power_spike_timing_stability"] < 0.5


def test_repeated_metric_rejects_divergent_tactical_permissions(
    monkeypatch: pytest.MonkeyPatch,
    hero: dict[str, Any],
    response: dict[str, Any],
) -> None:
    monkeypatch.setattr(
        generate_narratives,
        "validate_response",
        lambda *_args, **_kwargs: {},
    )
    unlocks = [
        "Area control permits forcing an objective.",
        "A protective effect permits surviving a counter-engage.",
        "Movement speed permits chasing an isolated target for a pick.",
    ]
    samples = []
    for attempt, unlock in enumerate(unlocks, start=1):
        divergent = copy.deepcopy(response)
        divergent["tactical_profile"]["power_spikes"][0]["tactical_unlock"] = unlock
        samples.append({
            "attempt": attempt,
            "duration_seconds": 30 + attempt,
            "output": divergent,
        })
    metric = metrics.RepeatedGenerationStabilityMetric(hero)

    score = metric.measure(_test_case(samples))

    assert score < metric.threshold
    assert not metric.is_successful()
    assert metric.score_breakdown["power_spike_tactical_stability"] == 0.0


def test_repeated_metric_rejects_missing_power_spikes(
    monkeypatch: pytest.MonkeyPatch,
    hero: dict[str, Any],
    response: dict[str, Any],
) -> None:
    monkeypatch.setattr(
        generate_narratives,
        "validate_response",
        lambda *_args, **_kwargs: {},
    )
    missing = copy.deepcopy(response)
    missing["tactical_profile"]["power_spikes"] = []
    samples = [
        {"attempt": attempt, "duration_seconds": 30 + attempt, "output": missing}
        for attempt in range(1, 4)
    ]
    metric = metrics.RepeatedGenerationStabilityMetric(hero)

    score = metric.measure(_test_case(samples))

    assert score < metric.threshold
    assert not metric.is_successful()
    assert metric.score_breakdown["power_spike_grounding"] == 0.0


def test_repeated_metric_rejects_duration_curve_contradiction(
    monkeypatch: pytest.MonkeyPatch,
    hero: dict[str, Any],
    response: dict[str, Any],
) -> None:
    monkeypatch.setattr(
        generate_narratives,
        "validate_response",
        lambda *_args, **_kwargs: {},
    )
    contradictory = copy.deepcopy(response)
    contradictory["tactical_profile"]["duration_plan"]["macro_plan"] = (
        "Intentionally stall every winnable game and refuse all earlier ending "
        "opportunities until the rare late tail."
    )
    samples = [
        {
            "attempt": attempt,
            "duration_seconds": 30 + attempt,
            "output": contradictory,
        }
        for attempt in range(1, 4)
    ]
    metric = metrics.RepeatedGenerationStabilityMetric(hero)

    score = metric.measure(_test_case(samples))

    assert score < metric.threshold
    assert not metric.is_successful()
    assert metric.score_breakdown["duration_curve_grounding"] == 0.0


def test_repeated_metric_scores_invocation_errors(
    monkeypatch: pytest.MonkeyPatch,
    hero: dict[str, Any],
    response: dict[str, Any],
) -> None:
    monkeypatch.setattr(
        generate_narratives,
        "validate_response",
        lambda *_args, **_kwargs: {},
    )
    samples = [
        {"attempt": 1, "duration_seconds": 31, "output": response},
        {"attempt": 2, "duration_seconds": 32, "output": response},
        {"attempt": 3, "duration_seconds": 120, "error": "Codex timed out"},
    ]
    metric = metrics.RepeatedGenerationStabilityMetric(hero)

    score = metric.measure(_test_case(samples))

    assert score < metric.threshold
    assert not metric.is_successful()
    assert metric.score_breakdown["completion"] == pytest.approx(2 / 3)
    assert "Codex timed out" in str(metric.reason)
