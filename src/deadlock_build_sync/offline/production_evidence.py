from __future__ import annotations

from datetime import datetime
from pathlib import Path

import duckdb

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

from .api import read_json, write_json
from .config import RunPaths, sha256_json
from .discovery_export import discover_roster
from .late_game import load_item_asset_maps
from .production_sources import (
    MINIMUM_CORE_SUPPORT,
    SCHEMA_VERSION,
    SEQUENCE_MINIMUM_SUPPORT,
    UnsupportedBuildPathError,
    _enemy_threat_evidence,
    _HeroExportContext,
    _patch_at,
    _rank_labels_sha256,
)
from .production_storage import _atomic_write, _folds_by_match


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
        core_economy_reference = {
            "target_core_cost": 19200,
            "basis": "frozen discovery maximum",
        }
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
    hero_payloads = discover_roster(heroes, export_context)
    if not any(hero["builds"] for hero in hero_payloads):
        report = paths.run / "discovery-exclusions.json"
        write_json(report, hero_payloads)
        raise UnsupportedBuildPathError(
            f"No builds passed. Existing artifact bundle is unchanged. Reasons: {report}"
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
                "Eclat four-to-six-item exact cores, Leiden groups, frozen selection "
                "ranking, corrected core outcomes, and supported pairwise order"
            ),
            "tier_membership": (
                "discovery buyers of the exact core; minimum 20 buyers, maximum 10 per tier"
            ),
            "tier_display_order": (
                "discovery median first-purchase time, then item id"
            ),
            "core_economy_reference": core_economy_reference,
            "outcome_usage": "freeze candidates, ranking, orders, and pools before corrected validation; reserved test data is not used",
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
        "mechanics_assets": normal_assets,
        "source_sha256": sources.get("source_sha256", {}),
        "frozen_data_sha256": manifest.get("frozen_data_sha256", {}),
        "requested_hero_ids": sorted(integer(hero["id"]) for hero in heroes),
        "heroes": hero_payloads,
    }
    document = {**payload, "artifact_id": sha256_json(payload)}
    _atomic_write(output, document)
    return document
