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
