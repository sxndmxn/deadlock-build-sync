from __future__ import annotations

from typing import TYPE_CHECKING

import duckdb
import polars as pl
import pytest

from deadlock_build_sync.offline.config import RunPaths
from tools.comparisons.legacy import analysis

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def _return(value: object) -> Callable[..., object]:
    def result(*_args: object, **_kwargs: object) -> object:
        return value

    return result


def _base_frame() -> pl.DataFrame:
    return pl.DataFrame({
        "hero_id": [1],
        "tier": [1],
        "item_id": [10],
        "value": [1.0],
    })


def _patch_analysis(
    monkeypatch: pytest.MonkeyPatch,
    *,
    include_ridge: bool,
) -> None:
    base = _base_frame()
    evaluation = pl.DataFrame({
        "model": ["baseline"],
        "observations": [10],
        "brier": [0.2],
        "log_loss": [0.4],
    })
    stability = pl.DataFrame({
        "hero_id": [1],
        "tier": [1],
        "method": ["adoption"],
        "shared_items": [3],
        "spearman": [0.8],
        "top10_jaccard": [0.7],
    })
    ridge_scores = base.rename({"value": "ridge_adjusted_rate"})
    if not include_ridge:
        ridge_scores = pl.DataFrame()
    ridge_evaluation = evaluation.with_columns(pl.lit("ridge").alias("model"))
    ridge_stability = stability.with_columns(pl.lit("ridge").alias("method"))
    if not include_ridge:
        ridge_evaluation = pl.DataFrame()
        ridge_stability = pl.DataFrame()

    monkeypatch.setattr(analysis, "_connection", _return(duckdb.connect()))
    monkeypatch.setattr(analysis, "_item_aggregates", _return(base))
    monkeypatch.setattr(analysis, "_add_intervals_and_eb", _return((base, [])))
    monkeypatch.setattr(
        analysis,
        "_state_adjusted",
        _return(base.rename({"value": "state_adjusted_eb"})),
    )
    monkeypatch.setattr(analysis, "_state_overlap_diagnostics", _return(base))
    monkeypatch.setattr(analysis, "_outcome_confounding_correlations", _return(base))
    monkeypatch.setattr(
        analysis,
        "_ridge_scores",
        _return((ridge_scores, ridge_evaluation, ridge_stability)),
    )
    monkeypatch.setattr(analysis, "_baseline_evaluation", _return(evaluation))
    monkeypatch.setattr(analysis, "_rank_stability", _return(stability))
    for name in (
        "_timing_window_stability",
        "_matchup_temporal_stability",
        "_purchase_state_coverage",
        "_sequence_model_evaluation",
        "_duration_profiles",
        "_match_bootstrap_intervals",
        "_account_breadth_stability",
    ):
        monkeypatch.setattr(analysis, name, _return(base))
    monkeypatch.setattr(analysis, "_matchups_and_transitions", _return((base, base)))
    monkeypatch.setattr(analysis, "_cohort_audits", _return((base, base, base)))
    monkeypatch.setattr(analysis, "_cohort_adoption_stability", _return((base, base)))
    monkeypatch.setattr(analysis, "_api_audit", _return((base, base)))
    monkeypatch.setattr(analysis, "_mechanics_audit", _return((base, base, base)))


@pytest.mark.parametrize("ridge_mode", ["with", "without"])
def test_analyze_writes_all_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ridge_mode: str,
) -> None:
    include_ridge = ridge_mode == "with"
    _patch_analysis(monkeypatch, include_ridge=include_ridge)
    paths = RunPaths.create(tmp_path, f"ridge-{include_ridge}")

    result = analysis.analyze(paths)

    assert result["items"] == 1
    assert result["ridge_scores"] == int(include_ridge)
    assert len(list(paths.tables.glob("*.csv"))) == 26
    assert (paths.tables / "full_eb_priors.json").exists()
    assert (paths.tables / "train_eb_priors.json").exists()
