from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from deadlock_build_sync.offline.config import RunPaths
from deadlock_build_sync.offline.production_sequence import _sequence_evaluation

if TYPE_CHECKING:
    from pathlib import Path


def test_sequence_evaluation_handles_missing_and_filters_hero_rows(
    tmp_path: Path,
) -> None:
    paths = RunPaths.create(tmp_path, "run")
    assert _sequence_evaluation(paths, 12) == []

    pl.DataFrame({
        "hero_id": [12, 13],
        "top1_accuracy": [0.75, 0.25],
        "test_decisions": [40, 20],
    }).write_csv(paths.tables / "sequence_model_evaluation.csv")

    assert _sequence_evaluation(paths, 12) == [
        {"hero_id": 12, "top1_accuracy": 0.75, "test_decisions": 40}
    ]
