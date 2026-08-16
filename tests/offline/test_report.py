import polars as pl

from deadlock_build_sync.offline.report import _format_scope_median


def test_scope_median_handles_sparse_or_null_stability() -> None:
    summary = pl.DataFrame({
        "scope": ["same_lane", "other"],
        "median_spearman": [None, 0.12345],
    })

    assert _format_scope_median(summary, "same_lane") == "unavailable"
    assert _format_scope_median(summary, "whole_enemy_team") == "unavailable"
    assert _format_scope_median(summary, "other") == "0.1235"
