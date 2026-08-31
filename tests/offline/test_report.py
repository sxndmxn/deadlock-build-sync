from dataclasses import replace
from pathlib import Path

import polars as pl
import pytest

from deadlock_build_sync.offline.report import _format_scope_median, render_report
from deadlock_build_sync.offline.report_core import build_core_report_context
from deadlock_build_sync.offline.report_helpers import (
    _event_inflation_bounds,
    _markdown_table,
)
from deadlock_build_sync.offline.report_paths import build_path_report_context
from tests.offline.report_fixtures import create_report_run, report_tables


def test_scope_median_handles_sparse_or_null_stability() -> None:
    summary = pl.DataFrame({
        "scope": ["same_lane", "other"],
        "median_spearman": [None, 0.12345],
    })

    assert _format_scope_median(summary, "same_lane") == "unavailable"
    assert _format_scope_median(summary, "whole_enemy_team") == "unavailable"
    assert _format_scope_median(summary, "other") == "0.1235"


def test_report_renders_tables_charts_and_markdown(tmp_path: Path) -> None:
    paths, _ = create_report_run(tmp_path)

    result = render_report(paths)

    report = paths.run.joinpath("REPORT.md").read_text(encoding="utf-8")
    assert result == {"report": str(paths.run / "REPORT.md"), "figures": 5}
    assert "Deadlock Item-Ranking Evidence Study" in report
    assert "Abrams" in report
    assert "The API reports an average" in report


def test_path_context_reports_non_unique_events_and_missing_kelvin() -> None:
    tables = report_tables()
    core = replace(
        build_core_report_context(tables),
        event_counts_are_unique=False,
        event_inflation_min=1.0,
        event_inflation_max=1.5,
    )
    tables = replace(tables, flow=tables.flow.filter(pl.col("hero_id") != 12))

    context = build_path_report_context(tables, core)

    assert "range from 1.00 to 1.50" in context.event_count_note
    assert context.kelvin_note == "No reconciled Kelvin Extra Charge row was available."


def test_report_validation_rejects_invalid_inputs() -> None:
    tables = report_tables()
    with pytest.raises(TypeError, match="cohort"):
        build_core_report_context(replace(tables, manifest={}))
    invalid_badges = replace(
        tables,
        cohort_badges=pl.DataFrame({
            "average_badge": pl.Series([None], dtype=pl.Int64),
            "player_matches": [1],
        }),
    )
    core = build_core_report_context(tables)
    with pytest.raises(TypeError, match="badge bounds"):
        build_path_report_context(invalid_badges, core)
    with pytest.raises(TypeError, match="not numeric"):
        _event_inflation_bounds(
            pl.DataFrame({
                "event_inflation": pl.Series([None], dtype=pl.Float64),
            })
        )


def test_markdown_table_escapes_text_and_formats_numbers() -> None:
    result = _markdown_table(
        pl.DataFrame({"name": ["a|b\nc"], "score": [0.125]}),
        [("name", "Name"), ("score", "Score")],
    )

    assert "a\\|b<br>c" in result
    assert "0.1250" in result
