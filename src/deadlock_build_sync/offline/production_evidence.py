from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb
from joblib import Parallel, delayed, parallel_config

from deadlock_build_sync.build_evidence import (
    MAXIMUM_TIER_ADOPTION_DRIFT,
    METHOD_VERSION,
    MINIMUM_IMBUE_SHARE,
    MINIMUM_IMBUE_SUPPORT,
    MINIMUM_PURCHASE_WINDOW_COVERAGE,
    MINIMUM_PURCHASE_WINDOW_OBSERVATIONS,
    MINIMUM_TIER_ADOPTION,
    TIER_ITEM_COUNT,
)
from deadlock_build_sync.mechanics import (
    BASE_INVENTORY_SLOTS,
    ItemGraph,
)
from deadlock_build_sync.value_validation import (
    integer,
    object_dict,
    object_rows,
)

from .api import read_json
from .build_paths import DiscoveredBuildPath, discover_build_paths
from .config import RunPaths, sha256_json
from .late_game import load_item_asset_maps
from .production_paths import _build_path_payload, _fallback_build_path
from .production_policy import (
    _core_economy_reference,
    _item_payload,
    _path_cohort_summary,
    _path_label,
    _tier_policy,
)
from .production_sequence import (
    _core_target_order,
    _expanded_default_path,
    _maximum_agreement_orders,
    _sequence_rows,
)
from .production_situational import _situational_policy
from .production_situational_data import (
    _situational_cells,
    _situational_selection_matchups,
    _situational_state_overlap,
)
from .production_sources import (
    DEFAULT_BUILD_PATH_LABEL,
    HERO_EXPORT_WORKERS,
    MINIMUM_CORE_SUPPORT,
    SCHEMA_VERSION,
    SEQUENCE_MINIMUM_SUPPORT,
    UnsupportedBuildPathError,
    _early_inventories_for_hero,
    _enemy_threat_evidence,
    _HeroExportContext,
    _inventories_for_hero,
    _patch_at,
    _patch_content_sha256,
    _rank_labels_sha256,
)
from .production_storage import _atomic_write, _core_decisions, _folds_by_match

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
    "export_production_evidence",
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


def export_production_evidence(paths: RunPaths, output: Path) -> dict[str, object]:
    manifest = object_dict(read_json(paths.run / "manifest.json"))
    if manifest is None:
        raise RuntimeError("analysis manifest must be a dictionary")
    cohort = object_dict(manifest.get("cohort"))
    sources = object_dict(manifest.get("sources"))
    if cohort is None or sources is None:
        raise RuntimeError("analysis manifest lacks frozen cohort or source identity")
    as_of = datetime.fromisoformat(str(cohort["as_of"]))
    heroes = object_rows(read_json(paths.raw / "heroes.json"))
    items_all = object_rows(read_json(paths.raw / "items-all.json"))
    if heroes is None or items_all is None:
        raise RuntimeError("hero and item assets must be lists of dictionaries")
    normal_assets = [
        item
        for item in items_all
        if isinstance(item, dict)
        and str(item.get("game_mode") or "normal").casefold() == "normal"
    ]
    item_assets, components = load_item_asset_maps(paths.raw / "items.json")
    item_graph = ItemGraph.from_assets(list(item_assets.values()))
    mechanics_assets_by_id = {
        integer(asset["id"]): asset
        for asset in normal_assets
        if isinstance(asset.get("id"), int)
    }
    item_costs = {
        item_id: integer(asset.get("cost"), default=0)
        for item_id, asset in item_assets.items()
    }
    con = duckdb.connect(str(paths.raw / "analysis.duckdb"), read_only=True)
    patch = _patch_at(paths, as_of)
    client_version = integer(sources["client_version"])
    try:
        folds_by_match = _folds_by_match(con)
        core_economy_reference = _core_economy_reference(con, cohort)
    finally:
        con.close()

    export_context = _HeroExportContext(
        paths=paths,
        hero_count=len(heroes),
        components=components,
        folds_by_match=folds_by_match,
        normal_assets=normal_assets,
        item_graph=item_graph,
        mechanics_assets_by_id=mechanics_assets_by_id,
        item_costs=item_costs,
        target_core_cost=integer(core_economy_reference["target_core_cost"]),
        enemy_threat_evidence=_enemy_threat_evidence(heroes, normal_assets),
    )
    hero_payloads = _parallel_hero_export(
        list(enumerate(heroes, start=1)),
        partial(_build_hero_payload, context=export_context),
    )

    epochs = {
        name: {
            "identity": str(patch["identity"]),
            "start_timestamp": integer(patch["start_timestamp"]),
        }
        for name in ("mechanics", "matchmaking", "map_objectives", "telemetry")
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "producer": "deadlock-build-sync.offline",
        "method": {
            "version": METHOD_VERSION,
            "minimum_core_item_count": 4,
            "maximum_core_item_count": BASE_INVENTORY_SLOTS,
            "minimum_core_support": MINIMUM_CORE_SUPPORT,
            "minimum_tier_support": SEQUENCE_MINIMUM_SUPPORT,
            "minimum_tier_adoption": MINIMUM_TIER_ADOPTION,
            "maximum_tier_adoption_drift": MAXIMUM_TIER_ADOPTION_DRIFT,
            "tier_item_count": TIER_ITEM_COUNT,
            "minimum_purchase_window_coverage": (MINIMUM_PURCHASE_WINDOW_COVERAGE),
            "minimum_purchase_window_observations": (
                MINIMUM_PURCHASE_WINDOW_OBSERVATIONS
            ),
            "minimum_imbue_support": MINIMUM_IMBUE_SUPPORT,
            "minimum_imbue_share": MINIMUM_IMBUE_SHARE,
            "core_selection": (
                "temporally stable supported four-to-six-item backbone, then a "
                "jointly supported mechanically legal completion of up to nine items "
                "within ten percent of the Oracle I+ economy target when available"
            ),
            "tier_membership": (
                "training adoption descending after fold support, five-percent "
                "adoption, ten-point drift, and upgrade-visibility gates"
            ),
            "tier_display_order": (
                "train-plus-validation median valid pre-purchase net worth, then "
                "median buy time and item id"
            ),
            "core_economy_reference": core_economy_reference,
            "outcome_usage": (
                "cross-fitted doubly robust contrasts may admit non-backbone CORE "
                "substitutions only after positive train and validation intervals, "
                "overlap, balance, ESS, uncertainty, and stability gates; the "
                "historical test fold also gates situational branch release and "
                "is not independent evaluation of the shipped policy"
            ),
            "independent_evaluation": "later replay states after the frozen artifact cutoff",
        },
        "cohort": {
            **cohort,
            "minimum_badge": integer(cohort["minimum_badge"]),
            "maximum_badge": integer(cohort["maximum_badge"]),
        },
        "patch": patch,
        "epochs": epochs,
        "client_version": client_version,
        "rank_labels_sha256": _rank_labels_sha256(paths),
        "heroes_sha256": sha256_json(heroes),
        "items_sha256": sha256_json(normal_assets),
        "source_sha256": sources.get("source_sha256", {}),
        "frozen_data_sha256": manifest.get("frozen_data_sha256", {}),
        "requested_hero_ids": sorted(integer(hero["id"]) for hero in heroes),
        "heroes": hero_payloads,
    }
    document = {**payload, "artifact_id": sha256_json(payload)}
    _atomic_write(output, document)
    return document
