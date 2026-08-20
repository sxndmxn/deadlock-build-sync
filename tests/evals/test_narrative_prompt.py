from __future__ import annotations

from copy import deepcopy

import pytest
from deepeval.evaluate import assert_test

from evals.metrics import production_metrics
from evals.narrative_eval import (
    NarrativeCase,
    generate_test_case,
    load_cases,
)

CASES = load_cases()


def _situational_case() -> NarrativeCase:
    hero = deepcopy(CASES[0].hero)
    tier = next(
        category
        for category in hero["projection"]["categories"]
        if category["optional"]
        and any(item["item"] == "Divine Barrier" for item in category["items"])
    )
    item = next(item for item in tier["items"] if item["item"] == "Divine Barrier")
    comparator = next(
        candidate
        for candidate in tier["items"]
        if candidate["item_id"] != item["item_id"]
    )
    evidence_ref = f"item/{item['item_id']}/situational/ally-protection"
    annotation = (
        f"If ally protection is needed, choose {item['item']} over "
        f"{comparator['item']}; activate on an ally; skip if no ally needs protection."
    )
    hero["explainable_actions"].append({
        "node_id": "situational-eval",
        "kind": "purchase",
        "action_id": item["item_id"],
        "action": item["item"],
        "evidence_ref": evidence_ref,
        "claim_class": "descriptive",
        "language_ceiling": ["associated", "observed"],
        "mechanics_refs": [f"item/{item['item_id']}/ally_protection"],
        "annotation": annotation,
        "conditional_contract": {
            "threat": "ally_protection",
            "item_id": item["item_id"],
            "item": item["item"],
            "comparator_item_id": comparator["item_id"],
            "comparator_item": comparator["item"],
            "enemy_hero_id": None,
            "mechanic_ref": f"item/{item['item_id']}/ally_protection",
            "legal_timing": "same observed decision opportunity",
            "alternative": f"{comparator['item']} or save",
            "replacement": f"Choose {item['item']} over {comparator['item']}.",
            "execution_mode": "Activate on an ally while protection is needed.",
            "failure_condition": "Skip if no ally needs protection.",
            "evidence_ref": evidence_ref,
        },
    })
    return NarrativeCase(hero, "closed situational branch contract")


def _optional_core_case() -> NarrativeCase:
    hero = deepcopy(CASES[0].hero)
    categories = hero["projection"]["categories"]
    tier = next(category for category in categories if category["name"] == "TIER 3")
    item = tier["items"].pop()
    core_item = hero["projection"]["categories"][0]["items"][-1]
    item["annotation"] = (
        f"Choose {item['item']} over {core_item['item']} only when its documented "
        "mechanic fits; keep the default when that need is absent."
    )
    categories.insert(
        1,
        {
            "name": "OPTIONAL CORE",
            "optional": True,
            "items": [item],
        },
    )
    policy = hero.get("policy")
    if isinstance(policy, dict):
        policy["schema_version"] = 2
        policy["core_alternatives"] = [
            {
                "item_id": item["item_id"],
                "comparator_item_id": core_item["item_id"],
                "stage": 8,
                "trigger": item["annotation"],
                "execution": (
                    f"Replace {core_item['item']} at the final supported slot."
                ),
                "failure_condition": (
                    f"Keep {core_item['item']} when the observable need is absent."
                ),
                "mechanics_refs": [f"asset:item:{item['item_id']}:description"],
                "evidence_ref": f"hero/{hero['hero_id']}/core-alternative/eval",
                "support": 200,
                "effective_support": 120.0,
                "overlap": 0.8,
                "interval": [-0.02, 0.02],
                "fold_estimates": {
                    "train": 0.0,
                    "validation": 0.01,
                    "test": -0.01,
                },
            }
        ]
    return NarrativeCase(hero, "optional core non-causal swap contract")


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_production_narrative_prompt(case: NarrativeCase) -> None:
    test_case = generate_test_case(case)
    assert_test(
        test_case,
        production_metrics(case.hero),
        run_async=False,
    )


def test_situational_narrative_prompt() -> None:
    case = _situational_case()
    test_case = generate_test_case(case)
    assert_test(test_case, production_metrics(case.hero), run_async=False)


def test_optional_core_narrative_prompt() -> None:
    case = _optional_core_case()
    test_case = generate_test_case(case)
    assert_test(test_case, production_metrics(case.hero), run_async=False)
