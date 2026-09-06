from __future__ import annotations

from deadlock_build_sync.offline.config import RunPaths

from .report_charts import _charts
from .report_core import build_core_report_context
from .report_data import load_report_tables
from .report_helpers import _format_scope_median
from .report_paths import build_path_report_context
from .report_render import render_report_text

__all__ = ["_format_scope_median", "render_report"]


def render_report(paths: RunPaths) -> dict[str, object]:
    _charts(paths)
    tables = load_report_tables(paths)
    core = build_core_report_context(tables)
    path = build_path_report_context(tables, core)
    report = render_report_text(paths, tables, core, path)
    target = paths.run / "REPORT.md"
    target.write_text(report, encoding="utf-8")
    return {"report": str(target), "figures": len(list(paths.figures.glob("*.png")))}
