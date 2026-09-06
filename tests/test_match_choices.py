from copy import deepcopy
from dataclasses import replace

import pytest

from deadlock_build_sync.artifacts import ArtifactError
from deadlock_build_sync.core_substitutions import validate_substitution_routes
from deadlock_build_sync.match_choices import MatchEconomy, parse_automatic_branches
from deadlock_build_sync.mechanics import ItemGraph
from deadlock_build_sync.purchase_branching import choose_route
from deadlock_build_sync.purchase_guidance_types import PurchaseState
from deadlock_build_sync.purchase_planner import first_checkpoint, plan_purchases
from deadlock_build_sync.recommendation_state import RecommendationError
from deadlock_build_sync.value_validation import (
    require_object_dict,
    require_object_rows,
)
from tests.discovery_fixtures import discovery_record
from tests.match_choice_fixtures import branch_document
from tests.purchase_guidance_fixtures import guidance_assets, guidance_fixture
from tests.recommendation_fixtures import state


@pytest.mark.parametrize(
    ("personal", "expected"),
    [(899, "behind"), (900, "even"), (1100, "even"), (1101, "ahead")],
)
def test_relative_wealth_boundaries(personal: int, expected: str) -> None:
    economy = MatchEconomy(personal, (1000,) * 12, 999)
    current = replace(state(), clock_s=1000, economy=economy)
    for condition in ("behind", "even", "ahead"):
        branch = parse_automatic_branches(
            branch_document(value=condition), {7}, (1, 3, 2, 4, 5)
        )[0]
        assert branch.matches(current) == (condition == expected)


@pytest.mark.parametrize(
    "economy",
    [
        MatchEconomy(None, (1000,) * 12, 999),
        MatchEconomy(800, (1000,) * 11, 999),
        MatchEconomy(800, (0,) * 12, 999),
        MatchEconomy(800, (1000,) * 12, None),
        MatchEconomy(800, (1000,) * 12, 1000),
        MatchEconomy(800, (1000,) * 12, 1001),
        MatchEconomy(800, (1000,) * 12, 699),
    ],
)
def test_missing_stale_or_future_wealth_disables_conditions(
    economy: MatchEconomy,
) -> None:
    assert economy.relative_wealth(1000) is None


@pytest.mark.parametrize("condition", ["enemy_hero", "enemy_item"])
def test_enemy_conditions_require_predecision_fresh_observation(condition: str) -> None:
    branch = parse_automatic_branches(
        branch_document(condition=condition, value=42), {7}, (1, 3, 2, 4, 5)
    )[0]
    current = replace(state(), clock_s=1000, enemy_hero_ids=(42,), enemy_item_ids=(42,))
    assert not branch.matches(current)
    assert branch.matches(replace(current, enemy_observed_at_s=700))
    assert not branch.matches(replace(current, enemy_observed_at_s=699))
    assert not branch.matches(replace(current, enemy_observed_at_s=1000))


def test_explicit_choices_precede_ranked_matching_branches_and_keep_liquid_cash() -> (
    None
):
    guide, graph = guidance_fixture()
    guidance = guide.purchase_guidance
    assert guidance is not None
    first = parse_automatic_branches(branch_document(), {7}, (1, 3, 2, 4, 5))[0]
    second = replace(first, item_id=8, lower_bound=0.09)
    guidance = replace(guidance, automatic_branches=(first, second))
    current = replace(
        state(),
        owned_items=(1, 3),
        clock_s=1000,
        liquid_souls=0,
        economy=MatchEconomy(8000, (10000,) * 12, 999),
    )
    selected = choose_route(guidance, current, graph, {})
    assert selected.positions == {8: 2}
    assert selected.source == "admitted matching branch"
    manual = choose_route(guidance, current, graph, {7: 2})
    assert manual.positions == {7: 2}
    assert manual.source == "explicit selection"
    plan = plan_purchases(
        graph,
        manual.path,
        manual.core,
        manual.positions,
        state=PurchaseState(current.owned_items, current.liquid_souls),
    )
    assert plan.decision == "save"
    assert plan.save_souls == plan.actions[0].incremental_cost
    assert (
        choose_route(guidance, replace(current, economy=None), graph, {}).source
        == "default path"
    )


def test_shared_component_occurrences_preserve_order_and_owned_upgrade_credit() -> None:
    _, graph = guidance_fixture()
    path = (1, 2, 1, 3, 6, 4, 5)
    core = (2, 3, 6, 4, 5)
    plan = plan_purchases(graph, path, core, {})
    assert tuple(step.item_id for step in plan.actions) == path
    owned = (2,)
    assert first_checkpoint(graph, path, owned) == 2
    remaining = plan_purchases(graph, path, core, {}, state=PurchaseState(owned))
    assert tuple(step.item_id for step in remaining.actions) == path[2:]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("support", 19),
        ("comparison_support", 19),
        ("effective_support", 19),
        ("overlap", 0.49),
        ("maximum_standardized_mean_difference", 0.11),
        ("interval", [0.0, 0.20]),
        ("estimate", float("nan")),
    ],
)
def test_branch_admission_rechecks_numeric_diagnostics(
    field: str, value: object
) -> None:
    document = branch_document()
    evidence = require_object_dict(
        require_object_rows(document["branches"])[0]["evidence"]
    )
    folds = require_object_dict(evidence["fold_diagnostics"])
    require_object_dict(folds["validation"])[field] = value
    with pytest.raises(ArtifactError, match="Automatic choice"):
        parse_automatic_branches(document, {7}, (1, 3, 2, 4, 5))


def test_core_substitution_requires_separate_core_admission_and_explicit_selection() -> (
    None
):
    guide, graph = guidance_fixture()
    guidance = guide.purchase_guidance
    assert guidance is not None
    document = branch_document()
    branch = require_object_rows(document["branches"])[0]
    core, path = [3, 7, 4, 5], [1, 3, 7, 4, 5]
    discovery = discovery_record(core, path)
    discovery["identity_id"] = "separate-core"
    branch["substitution"] = {
        "source_identity_id": "separate-core",
        "core": core,
        "path": path,
        "discovery": discovery,
    }
    loaded = parse_automatic_branches(document, {7}, (1, 3, 2, 4, 5))[0]
    validate_substitution_routes(graph, (), guidance.core_ids)
    with pytest.raises(ArtifactError, match="invalid component path"):
        validate_substitution_routes(graph, (loaded,), guidance.core_ids)
    assets = guidance_assets()
    next(asset for asset in assets if asset["id"] == 7)["component_items"] = ["Sprint"]
    graph = ItemGraph.from_assets(assets)
    validate_substitution_routes(graph, (loaded,), guidance.core_ids)
    with pytest.raises(ArtifactError, match="separate evidence"):
        validate_substitution_routes(
            graph, (replace(loaded, substitution_evidence={}),), guidance.core_ids
        )
    with pytest.raises(ArtifactError, match="invalid component path"):
        validate_substitution_routes(
            graph, (replace(loaded, comparator_item_id=3),), guidance.core_ids
        )
    guidance = replace(guidance, automatic_branches=(loaded,))
    current = replace(state(), core_substitution_item_id=7)
    with pytest.raises(RecommendationError, match="explicit item selection"):
        choose_route(guidance, current, graph, {})
    chosen = choose_route(guidance, current, graph, {7: 2})
    assert chosen.core == tuple(core)
    changed = deepcopy(document)
    raw = require_object_dict(
        require_object_rows(changed["branches"])[0]["substitution"]
    )
    require_object_dict(raw["discovery"])["rejections"] = ["weak outcome"]
    with pytest.raises(ArtifactError, match="rejected discovery"):
        parse_automatic_branches(changed, {7}, (1, 3, 2, 4, 5))


@pytest.mark.parametrize(
    ("field", "value"), [("condition", {}), ("value", []), ("condition", "unknown")]
)
def test_malformed_branch_conditions_are_artifact_errors(
    field: str, value: object
) -> None:
    document = branch_document()
    require_object_rows(document["branches"])[0][field] = value
    with pytest.raises(ArtifactError, match="Automatic choice"):
        parse_automatic_branches(document, {7}, (1, 3, 2, 4, 5))
