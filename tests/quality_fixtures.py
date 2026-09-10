from __future__ import annotations

import json
from dataclasses import asdict

from tests.recommendation_fixtures import (
    make_decision_state,
    make_recommendation_policy,
)


def make_replay_row() -> dict[str, object]:
    document = asdict(make_decision_state())
    document["schema_version"] = 3
    document["inventory"] = {
        "items": document.pop("owned_items"),
        "components": document.pop("owned_components"),
        "open_slots": document.pop("open_slots"),
        "flex_slots": document.pop("unlocked_flex_slots"),
        "active_bindings": document.pop("active_bindings"),
    }
    return {
        "policy_id": make_recommendation_policy().policy_id,
        "match_group": "deidentified-match",
        "match_start_timestamp": 2000,
        "policy_assigned_at": 1990,
        "feature_as_of_timestamp": 2200,
        "state": json.loads(json.dumps(document)),
        "observed_action": "buy",
        "observed_item_id": 1,
        "core_completed": False,
        "behind": True,
        "ambiguous_purchase": False,
    }


def make_replay_document(rows: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "cohort_selection": "all_eligible_player_matches",
        "cases": rows,
    }
