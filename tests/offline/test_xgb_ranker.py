from collections import Counter

import polars as pl

from deadlock_build_sync.offline.xgb_ranker import (
    Asset,
    BaselineCounts,
    PurchaseQuery,
    _apply_purchase,
    _expand_component_path,
    _gate,
    sample_queries,
    sampled_candidates,
)


def _assets() -> tuple[list[Asset], dict[int, Asset]]:
    assets = [
        Asset(1, 0, "Component", 1, 800, "spirit", 0, False, False, ()),
        Asset(2, 1, "Upgrade", 2, 1600, "spirit", 0, False, False, (1,)),
        Asset(3, 2, "Alternative", 1, 800, "weapon", 1, False, False, ()),
    ]
    return assets, {asset.item_id: asset for asset in assets}


def _query(position: int, fold: str = "train", target: int = 2) -> PurchaseQuery:
    return PurchaseQuery(
        match_id=position + 1,
        player_slot=0,
        fold=fold,
        position=position,
        phase=0,
        first_item=1,
        previous_item=1,
        current_time_s=200,
        prior_spend=800,
        own_net_worth=2000,
        team_lead=None,
        average_badge=80,
        calibration=False,
        owned=(1,),
        target=target,
        target_buy_time_s=300,
        component_upgrade=True,
    )


def test_sampling_is_deterministic_and_preserves_folds() -> None:
    queries = [_query(index, "test") for index in range(50)]

    first = sample_queries(queries, "test", 10)
    second = sample_queries(list(reversed(queries)), "test", 10)

    assert first == second
    assert len(first) == 10
    assert all(query.fold == "test" for query in first)


def test_candidate_group_contains_one_positive_and_no_owned_item() -> None:
    assets, by_id = _assets()
    queries = [_query(0), _query(1, target=3)]
    baseline = BaselineCounts.fit(queries, len(assets))

    candidates = sampled_candidates(
        queries[0], baseline=baseline, assets=assets, by_id=by_id
    )

    assert candidates.count(queries[0].target) == 1
    assert 1 not in candidates


def test_component_path_uses_incremental_cost_and_finishes_exactly() -> None:
    _, by_id = _assets()
    actions, cost = _expand_component_path([2, 3], by_id)

    assert [action["item"] for action in actions] == [
        "Component",
        "Upgrade",
        "Alternative",
    ]
    assert [action["incremental_souls"] for action in actions] == [800, 800, 800]
    assert cost == 2400

    owned = {1}
    assert _apply_purchase(2, owned, by_id) == 800
    assert owned == {2}


def test_baseline_counts_use_train_only() -> None:
    train = _query(0, "train", 2)
    test = _query(1, "test", 3)
    baseline = BaselineCounts.fit([train, test], 3)

    assert baseline.popularity == Counter({2: 1})


def test_promotion_gate_rejects_material_per_hero_regression() -> None:
    rows = []
    for hero_id, queries, baseline_mrr, xgb_mrr in (
        (1, 100, 0.30, 0.40),
        (2, 1, 0.50, 0.47),
    ):
        for subset in ("all", "non_component"):
            for model, mrr in (("baseline", baseline_mrr), ("xgboost", xgb_mrr)):
                lift = 0.10 if model == "xgboost" else 0.0
                rows.append({
                    "hero_id": hero_id,
                    "fold": "test",
                    "subset": subset,
                    "model": model,
                    "queries": queries,
                    "top1": mrr,
                    "top3": 0.50 + lift,
                    "top5": 0.60 + lift,
                    "mrr": mrr,
                    "ndcg5": 0.50 + lift,
                })

    gate = _gate(
        pl.DataFrame(rows),
        {"mrr_delta": 0.09, "lower": 0.08, "upper": 0.10},
    )

    assert gate["non_component_mrr_delta"] > 0.01
    assert gate["worst_hero_mrr_delta"] < -0.02
    assert gate["passed"] is False
