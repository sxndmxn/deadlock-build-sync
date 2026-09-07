from __future__ import annotations

import json
from typing import TYPE_CHECKING

import duckdb
import polars as pl
import pytest

from deadlock_build_sync.artifacts import ArtifactError
from deadlock_build_sync.offline import core_policy_dr
from deadlock_build_sync.offline import production_storage as storage
from deadlock_build_sync.offline.config import sha256_json
from deadlock_build_sync.value_validation import integer
from tests.build_evidence_fixtures import _document, _refingerprint
from tests.mechanics_fixtures import item
from tests.offline.production_evidence_fixtures import _item_graph
from tools.comparisons.legacy import production_storage as legacy_storage

if TYPE_CHECKING:
    from pathlib import Path

    from deadlock_build_sync.mechanics import ItemGraph


def test_atomic_write_replaces_document_and_cleans_failed_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "nested/document.json"
    storage._atomic_write(target, {"value": 1})
    assert json.loads(target.read_text(encoding="utf-8")) == {"value": 1}

    failed = tmp_path / "failed/document.json"
    monkeypatch.setattr(storage.os, "fsync", _fail_fsync)
    with pytest.raises(OSError, match="sync failed"):
        storage._atomic_write(failed, {"value": 2})
    assert not failed.exists()
    assert list(failed.parent.glob("*.tmp")) == []


def _fail_fsync(_descriptor: int) -> None:
    raise OSError("sync failed")


def test_invalid_replacement_evidence_preserves_current_artifact(
    tmp_path: Path,
) -> None:
    target = tmp_path / "build-evidence.json"
    document = _document()
    storage.validated_write(target, document)
    previous = target.read_bytes()
    document["schema_version"] = 10
    _refingerprint(document)
    with pytest.raises(ArtifactError, match="refresh-evidence"):
        storage.validated_write(target, document)
    assert target.read_bytes() == previous
    assert list(tmp_path.iterdir()) == [target]


def test_fold_and_decision_queries_return_typed_data() -> None:
    con = duckdb.connect()
    try:
        con.execute("CREATE TABLE match_folds(match_id INTEGER, fold VARCHAR)")
        con.execute("INSERT INTO match_folds VALUES (1, 'train'), (2, 'test')")
        con.execute(
            """
            CREATE TABLE decision_opportunities AS SELECT
                1 AS match_id, 0 AS player_slot, 'train' AS fold,
                3 AS item_id, true AS won, 90 AS average_badge,
                1 AS phase, 600 AS buy_time, 10000 AS own_net_worth_at_buy,
                590 AS state_observed_at_s, 50000 AS own_team_net_worth,
                49000 AS enemy_team_net_worth, 1000 AS team_net_worth_lead,
                10 AS state_age_s, 5000 AS prior_catalog_spend,
                2 AS prior_purchase_count, 7 AS hero_id
            """
        )

        folds = storage._folds_by_match(con)
        decisions = legacy_storage._core_decisions(con, 7)
    finally:
        con.close()

    assert folds == {1: "train", 2: "test"}
    assert decisions.height == 1
    assert decisions["item_id"].item() == 3


def _metrics() -> dict[int, dict[str, object]]:
    return {
        item_id: {
            "item_id": item_id,
            "item_name": f"Item {item_id}",
            "tier": 1,
            "adopter_matches": 40 - item_id,
            "selection_adopter_matches": 40 - item_id,
        }
        for item_id in (1, 2, 3, 4)
    }


def test_core_candidate_and_best_alternative_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(legacy_storage, "_replacement_is_legal", _legal_replacement)
    metrics = _metrics()
    candidates = legacy_storage._core_alternative_candidates(
        metrics,
        (1, 2),
        {1, 2},
        2,
        metrics[2],
        _item_graph({}),
        {},
    )
    assert [row["item_id"] for row in candidates] == [3, 4]

    alternatives: list[dict[str, object]] = [
        {
            "item_id": 3,
            "stage": 2,
            "effective_support": 30,
            "comparative_interval": [0.01, 0.03],
        },
        {
            "item_id": 3,
            "stage": 3,
            "effective_support": 20,
            "comparative_interval": [0.0, 0.05],
        },
        {
            "item_id": 4,
            "stage": 1,
            "effective_support": 25,
            "comparative_interval": [0.01, 0.02],
        },
    ]
    best = legacy_storage._best_core_alternatives_by_item(alternatives)
    assert [(row["item_id"], row["stage"]) for row in best] == [(4, 1), (3, 2)]
    with pytest.raises(TypeError, match="two values"):
        legacy_storage._best_core_alternatives_by_item([
            {**alternatives[0], "comparative_interval": [0.1]}
        ])


def _legal_replacement(
    _default: tuple[int, ...],
    _comparator: int,
    _candidate: int,
    _graph: ItemGraph,
    _priorities: dict[int, tuple[float, float, int]],
) -> bool:
    return True


def _conditional(
    candidate: dict[str, object],
    _comparator: dict[str, object],
) -> tuple[str, str, str, str] | None:
    if integer(candidate["id"]) == 3:
        return None
    return ("Threat", "Reason", "When", "Skip")


def _contrast(
    _decisions: pl.DataFrame,
    item_id: int,
    comparator_id: int,
) -> core_policy_dr.DrContrast:
    return core_policy_dr.DrContrast(
        treatment_item_id=item_id,
        comparator_item_id=comparator_id,
        support=30,
        comparison_support=30,
        effective_support=25.0,
        overlap=0.8,
        maximum_weight=2.0,
        maximum_standardized_mean_difference=0.05,
        estimate=0.05,
        interval=(0.01, 0.09),
        fold_estimates={"train": 0.05, "validation": 0.04},
        fold_diagnostics={},
        clipped_sensitivity={"5": 0.05},
        stable=True,
        admitted=True,
        failed_gates=(),
    )


def _raise_contrast(
    _decisions: pl.DataFrame,
    _item_id: int,
    _comparator_id: int,
) -> core_policy_dr.DrContrast:
    raise RuntimeError("not estimable")


def test_core_alternatives_audit_mechanics_estimability_and_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _item_graph({})
    hero_metrics = pl.DataFrame(list(_metrics().values()))
    assets = {item_id: item(item_id, f"item_{item_id}") for item_id in (1, 2, 3, 4)}
    monkeypatch.setattr(legacy_storage, "_replacement_is_legal", _legal_replacement)
    monkeypatch.setattr(legacy_storage, "conditional_item_decision", _conditional)
    monkeypatch.setattr(legacy_storage, "cross_fitted_dr_contrast", _contrast)

    admitted, audit = legacy_storage._core_alternatives(
        pl.DataFrame({"item_id": [3, 4], "fold": ["train", "validation"]}),
        (1, 2),
        (1,),
        hero_metrics,
        assets,
        graph,
        {},
    )

    assert [row["item_id"] for row in admitted] == [4]
    assert len(audit) == 2
    assert audit[0]["failed_gates"] == ["mechanics_grounding"]
    assert admitted[0]["swap"] == "Replaces Item 2"
    assert sha256_json({"admitted": admitted, "audit": audit}) == (
        "41ce216c1c81f5e8c9039db54bca362b43390ec816fb019f8d529bee91e3dc16"
    )

    monkeypatch.setattr(legacy_storage, "cross_fitted_dr_contrast", _raise_contrast)
    _, failed_audit = legacy_storage._core_alternatives(
        pl.DataFrame({"item_id": [3, 4], "fold": ["train", "validation"]}),
        (1, 2),
        (1,),
        hero_metrics,
        assets,
        graph,
        {},
    )
    assert failed_audit[1]["failed_gates"] == ["estimability"]
