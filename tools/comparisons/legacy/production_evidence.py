from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from typing import TYPE_CHECKING

import duckdb
from deadlock_build_sync.offline.production_sources import (
    DEFAULT_BUILD_PATH_LABEL,
    HERO_EXPORT_WORKERS,
    UnsupportedBuildPathError,
    _early_inventories_for_hero,
    _HeroExportContext,
    _inventories_for_hero,
    _patch_content_sha256,
)
from deadlock_build_sync.value_validation import (
    integer,
)
from joblib import Parallel, delayed, parallel_config

from tools.comparisons.legacy.production_policy import (
    _core_economy_reference,
    _item_payload,
    _path_cohort_summary,
    _tier_policy,
)
from tools.comparisons.legacy.production_sequence import (
    _core_target_order,
    _expanded_default_path,
    _maximum_agreement_orders,
    _sequence_rows,
)
from tools.comparisons.legacy.production_situational import _situational_policy
from tools.comparisons.legacy.production_situational_data import (
    _situational_cells,
    _situational_selection_matchups,
    _situational_state_overlap,
)
from tools.comparisons.legacy.production_storage import (
    _core_decisions,
)

from .build_paths import DiscoveredBuildPath, discover_build_paths
from .production_paths import _build_path_payload, _fallback_build_path
from .production_policy import _path_label

if TYPE_CHECKING:
    import polars as pl

__all__ = [
    "UnsupportedBuildPathError",
    "_HeroExportContext",
    "_core_economy_reference",
    "_core_target_order",
    "_expanded_default_path",
    "_item_payload",
    "_maximum_agreement_orders",
    "_parallel_hero_export",
    "_patch_content_sha256",
    "_path_cohort_summary",
    "_path_payloads",
    "_sequence_rows",
    "_situational_policy",
    "_situational_selection_matchups",
    "_tier_policy",
]


def _parallel_hero_export(
    jobs: list[tuple[int, dict[str, object]]],
    worker: Callable[[tuple[int, dict[str, object]]], dict[str, object]],
) -> list[dict[str, object]]:
    worker_count = min(HERO_EXPORT_WORKERS, len(jobs))
    with parallel_config(
        backend="loky",
        n_jobs=worker_count,
        inner_max_num_threads=1,
    ):
        return Parallel()(delayed(worker)(job) for job in jobs)


def _path_payloads(
    con: duckdb.DuckDBPyConnection,
    hero_id: int,
    hero: dict[str, object],
    paths: tuple[DiscoveredBuildPath, ...],
    inventories: dict[tuple[int, int], tuple[int, ...]],
    context: _HeroExportContext,
    *,
    core_decisions: pl.DataFrame | None = None,
    situational_evidence: tuple[pl.DataFrame, pl.DataFrame] | None = None,
) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    labels = [_path_label(con, path, context.mechanics_assets_by_id) for path in paths]
    label_counts = Counter(labels)
    payloads: list[dict[str, object]] = []
    abstentions: list[dict[str, str]] = []
    for path, label in zip(paths, labels, strict=True):
        try:
            payloads.append(
                _build_path_payload(
                    con,
                    hero_id,
                    hero,
                    path,
                    label,
                    label_counts,
                    inventories,
                    context,
                    core_decisions,
                    situational_evidence,
                )
            )
        except UnsupportedBuildPathError as error:
            abstentions.append({
                "path_id": path.path_id,
                "reason": str(error),
            })
    if payloads:
        return payloads, abstentions
    fallback = _fallback_build_path(inventories, context.folds_by_match)
    return (
        [
            _build_path_payload(
                con,
                hero_id,
                hero,
                fallback,
                DEFAULT_BUILD_PATH_LABEL,
                Counter({DEFAULT_BUILD_PATH_LABEL: 1}),
                inventories,
                context,
                core_decisions,
                situational_evidence,
            )
        ],
        abstentions,
    )


def _build_hero_payload(
    job: tuple[int, dict[str, object]],
    *,
    context: _HeroExportContext,
) -> dict[str, object]:
    index, hero = job
    con = duckdb.connect(str(context.paths.raw / "analysis.duckdb"), read_only=True)
    con.execute("SET threads = 1")
    try:
        hero_id = integer(hero["id"])
        name = str(hero.get("name") or hero_id)
        print(
            f"Production evidence {index}/{context.hero_count} started: {name}",
            flush=True,
        )
        inventories = _inventories_for_hero(con, hero_id, context.components)
        paths = discover_build_paths(
            inventories,
            _early_inventories_for_hero(con, hero_id),
            context.folds_by_match,
        )
        core_decisions = _core_decisions(con, hero_id)
        situational_evidence = (
            _situational_state_overlap(con, hero_id),
            _situational_cells(con, hero_id, selection_only=False),
        )
        builds, path_abstentions = _path_payloads(
            con,
            hero_id,
            hero,
            paths,
            inventories,
            context,
            core_decisions=core_decisions,
            situational_evidence=situational_evidence,
        )
        payload = {
            "hero_id": hero_id,
            "hero": name,
            "builds": builds,
            "path_abstentions": path_abstentions,
        }
        print(
            f"Production evidence {index}/{context.hero_count} completed: {name}",
            flush=True,
        )
        return payload
    finally:
        con.close()
