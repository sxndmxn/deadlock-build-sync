from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from deadlock_build_sync.build_evidence import load_build_evidence
from deadlock_build_sync.match_choices import MatchEconomy
from deadlock_build_sync.recommendation_plan import (
    recommend_guide,
    recommendation_markdown,
    selected_positions,
)
from deadlock_build_sync.recommendation_state import (
    RecommendationAction,
    RecommendationError,
)
from deadlock_build_sync.value_validation import (
    require_object_dict,
    require_object_rows,
)
from tests.build_evidence_fixtures import _assets, _document, _write
from tests.purchase_guidance_fixtures import guidance_fixture
from tests.recommendation_fixtures import build_policy, state

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"placement_overrides": {7: 2}}, "refer to selected"),
        ({"selected_optional_items": (99,)}, "outside this identity"),
        ({"selected_optional_items": (9,)}, "Timing unknown"),
    ],
)
def test_manual_selections_need_pool_membership_and_supported_timing(
    changes: dict[str, object], message: str
) -> None:
    guide, _ = guidance_fixture()
    assert guide.purchase_guidance is not None
    with pytest.raises(RecommendationError, match=message):
        selected_positions(guide.purchase_guidance, state(**changes))
    assert selected_positions(
        guide.purchase_guidance,
        state(selected_optional_items=(7, 9), placement_overrides={9: 4}),
    ) == {7: 2, 9: 4}


def test_recommendation_replans_combined_choices_and_returns_complete_pool(
    tmp_path: Path,
) -> None:
    path = tmp_path / "evidence.json"
    _write(path, _document())
    evidence = load_build_evidence(path).heroes[13]
    policy = replace(build_policy(), hero_id=13, path_id=evidence.path_id)
    current = state(
        hero_id=13,
        path_id=evidence.path_id,
        owned_items=(101,),
        liquid_souls=0,
        selected_optional_items=(103, 104),
        placement_overrides={103: 1, 104: 2},
        economy=MatchEconomy(8000, (10000,) * 12, 299),
    )
    decision = recommend_guide(evidence, policy, current, _assets())
    assert decision.action is RecommendationAction.SAVE
    details = require_object_dict(decision.purchase_plan)
    assert details["path_id"] == evidence.path_id
    assert details["relative_wealth"] == 0.8
    assert details["selected_placements"] == {"103": 1, "104": 2}
    steps = require_object_rows(details["remaining_route"])
    assert [step["item_id"] for step in steps][:3] == [103, 102, 104]
    assert details["cash_shortfall"] == steps[0]["incremental_cost"]
    choices = require_object_rows(details["available_choices"])
    assert len(choices) == 37
    assert all(
        "instruction" in choice and "current_plan" in choice for choice in choices
    )
    markdown = recommendation_markdown(decision)
    assert "Cash shortfall: 1000 souls" in markdown
    assert all(str(choice["name"]) in markdown for choice in choices)
    bought = recommend_guide(
        evidence, policy, replace(current, liquid_souls=1000), _assets()
    )
    assert bought.action is RecommendationAction.BUY
    done = recommend_guide(
        evidence,
        policy,
        state(hero_id=13, owned_items=(101, 102, 201, 202, 301, 302)),
        _assets(),
    )
    assert done.action is RecommendationAction.END
    assert require_object_dict(done.purchase_plan)["next_purchase"] is None


def test_recommendation_rejects_changed_identity_and_illegal_placements(
    tmp_path: Path,
) -> None:
    path = tmp_path / "evidence.json"
    _write(path, _document())
    evidence = load_build_evidence(path).heroes[13]
    policy = replace(build_policy(), hero_id=13, path_id=evidence.path_id)
    with pytest.raises(RecommendationError, match="different build identities"):
        recommend_guide(evidence, policy, state(path_id="another"), _assets())
    with pytest.raises(RecommendationError, match="position"):
        recommend_guide(
            evidence,
            policy,
            state(selected_optional_items=(103,), placement_overrides={103: 99}),
            _assets(),
        )
