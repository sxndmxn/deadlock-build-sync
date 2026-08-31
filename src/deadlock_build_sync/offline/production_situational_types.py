from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import polars as pl

type QualifiedSituationalBranch = tuple[
    tuple[float, ...],
    dict[str, object],
    dict[str, object],
]
type SituationalEvidence = tuple[
    pl.DataFrame,
    dict[int, dict[str, object]],
    dict[object, dict[str, object]],
]
