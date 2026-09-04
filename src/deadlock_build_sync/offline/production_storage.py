from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

from deadlock_build_sync.mechanics import (
    ItemGraph,
    conditional_item_decision,
)
from deadlock_build_sync.mechanics_compatibility import (
    asset_mechanics_refs,
)
from deadlock_build_sync.value_validation import (
    integer,
    number,
    object_list,
)

from .core_policy import (
    cross_fitted_dr_contrast,
)
from .core_policy_config import SELECTION_FOLDS
from .production_sequence import _replacement_is_legal
from .production_sources import MINIMUM_CORE_SUPPORT

if TYPE_CHECKING:
    import duckdb


def _atomic_write(path: Path, document: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode()
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
        temporary = None
        descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _folds_by_match(con: duckdb.DuckDBPyConnection) -> dict[int, str]:
    return {
        int(match_id): str(fold)
        for match_id, fold in con.execute(
            "SELECT match_id, fold FROM match_folds"
        ).fetchall()
    }


def _core_decisions(con: duckdb.DuckDBPyConnection, hero_id: int) -> pl.DataFrame:
    arrow = con.execute(
        """
        SELECT match_id, player_slot, fold, item_id, won, average_badge,
               phase, buy_time, own_net_worth_at_buy, state_observed_at_s,
               own_team_net_worth, enemy_team_net_worth, team_net_worth_lead,
               state_age_s, prior_catalog_spend, prior_purchase_count
        FROM decision_opportunities
        WHERE hero_id = ?
        """,
        [hero_id],
    ).to_arrow_table()
    frame = pl.from_arrow(arrow)
    if not isinstance(frame, pl.DataFrame):
        raise RuntimeError("decision query did not return a table")
    return frame


def _core_alternative_candidates(
    metrics: dict[int, dict[str, object]],
    default_item_ids: tuple[int, ...],
    default_set: set[int],
    comparator_id: int,
    comparator: dict[str, object],
    graph: ItemGraph,
    priorities: dict[int, tuple[float, float, int]],
) -> list[dict[str, object]]:
    candidates = (
        row
        for item_id, row in metrics.items()
        if item_id not in default_set
        and integer(row["tier"]) == integer(comparator["tier"])
        and integer(row["selection_adopter_matches"]) >= MINIMUM_CORE_SUPPORT
        and _replacement_is_legal(
            default_item_ids,
            comparator_id,
            item_id,
            graph,
            priorities,
        )
    )
    return sorted(
        candidates,
        key=lambda row: (
            -integer(row["selection_adopter_matches"]),
            integer(row["item_id"]),
        ),
    )[:2]


def _best_core_alternatives_by_item(
    alternatives: list[dict[str, object]],
) -> list[dict[str, object]]:
    best_by_item: dict[int, dict[str, object]] = {}
    rankings: dict[int, tuple[float, float, int]] = {}
    for row in alternatives:
        item_id = integer(row["item_id"])
        interval = object_list(row["comparative_interval"])
        if interval is None or len(interval) != 2:
            raise TypeError("comparative interval must contain two values")
        ranking = (
            number(row["effective_support"]),
            -(number(interval[1]) - number(interval[0])),
            -integer(row["stage"]),
        )
        if item_id not in rankings or ranking > rankings[item_id]:
            best_by_item[item_id] = row
            rankings[item_id] = ranking
    return sorted(
        best_by_item.values(),
        key=lambda row: (integer(row["stage"]), integer(row["item_id"])),
    )


def _core_alternatives(
    decisions: pl.DataFrame,
    default_item_ids: tuple[int, ...],
    backbone_item_ids: tuple[int, ...],
    hero_metrics: pl.DataFrame,
    item_assets: dict[int, dict[str, object]],
    graph: ItemGraph,
    priorities: dict[int, tuple[float, float, int]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    decisions = decisions.filter(pl.col("fold").is_in(SELECTION_FOLDS))
    metrics = {
        integer(row["item_id"]): row for row in hero_metrics.iter_rows(named=True)
    }
    default_set = set(default_item_ids)
    backbone_set = set(backbone_item_ids)
    alternatives: list[dict[str, object]] = []
    audit: list[dict[str, object]] = []
    for stage, comparator_id in enumerate(default_item_ids, start=1):
        if comparator_id in backbone_set:
            continue
        comparator = metrics[comparator_id]
        candidates = _core_alternative_candidates(
            metrics,
            default_item_ids,
            default_set,
            comparator_id,
            comparator,
            graph,
            priorities,
        )
        for candidate in candidates:
            item_id = integer(candidate["item_id"])
            decision = conditional_item_decision(
                item_assets[item_id],
                item_assets[comparator_id],
            )
            if decision is None:
                audit.append({
                    "item_id": item_id,
                    "comparator_item_id": comparator_id,
                    "stage": stage,
                    "admitted": False,
                    "failed_gates": ["mechanics_grounding"],
                    "reason": (
                        "item and comparator do not support a concrete "
                        "conditional decision"
                    ),
                })
                continue
            try:
                contrast = cross_fitted_dr_contrast(decisions, item_id, comparator_id)
            except (RuntimeError, ValueError) as error:
                audit.append({
                    "item_id": item_id,
                    "comparator_item_id": comparator_id,
                    "stage": stage,
                    "admitted": False,
                    "failed_gates": ["estimability"],
                    "reason": str(error),
                })
                continue
            record: dict[str, object] = {
                "item_id": item_id,
                "comparator_item_id": comparator_id,
                "stage": stage,
                "support": contrast.support,
                "comparison_support": contrast.comparison_support,
                "effective_support": contrast.effective_support,
                "overlap": contrast.overlap,
                "maximum_weight": contrast.maximum_weight,
                "maximum_standardized_mean_difference": (
                    contrast.maximum_standardized_mean_difference
                ),
                "dr_estimate": contrast.estimate,
                "comparative_interval": list(contrast.interval),
                "fold_estimates": contrast.fold_estimates,
                "fold_diagnostics": contrast.fold_diagnostics,
                "clipped_sensitivity": contrast.clipped_sensitivity,
                "stable": contrast.stable,
                "admitted": contrast.admitted,
                "failed_gates": list(contrast.failed_gates),
            }
            audit.append(record)
            if not contrast.admitted:
                continue
            comparator_name = str(comparator["item_name"])
            refs = asset_mechanics_refs(item_assets[item_id])
            comparator_refs = asset_mechanics_refs(item_assets[comparator_id])
            vs, why, when, skip = decision
            alternatives.append({
                **record,
                "vs": vs,
                "why": why,
                "swap": f"Replaces {comparator_name}",
                "when": when,
                "skip": skip,
                "mechanics_refs": list(refs),
                "comparator_mechanics_refs": list(comparator_refs),
            })
    admitted = _best_core_alternatives_by_item(alternatives)
    return admitted[:10], audit
