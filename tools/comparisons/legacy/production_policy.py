from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

import polars as pl
from deadlock_build_sync.build_evidence import (
    MAXIMUM_TIER_ADOPTION_DRIFT,
    MINIMUM_PURCHASE_WINDOW_COVERAGE,
    MINIMUM_PURCHASE_WINDOW_OBSERVATIONS,
    MINIMUM_TIER_ADOPTION,
    TIER_ITEM_COUNT,
    TIER_POLICY_VERSION,
)
from deadlock_build_sync.mechanics import (
    MAX_FLEX_SLOTS,
    ItemGraph,
)
from deadlock_build_sync.offline.production_sources import (
    CORE_ECONOMY_REFERENCE_MINIMUM_BADGE,
    DEFAULT_BUILD_PATH_LABEL,
    MINIMUM_CORE_SUPPORT,
    UnsupportedBuildPathError,
)
from deadlock_build_sync.value_validation import (
    integer,
    number,
)

from .build_paths import DiscoveredBuildPath

if TYPE_CHECKING:
    import duckdb


from deadlock_build_sync.offline.production_items import (
    _item_payload,
    _optional_float,
    _path_cohort_summary,
)

__all__ = ["_item_payload", "_optional_float", "_path_cohort_summary"]


def _core_economy_reference(
    con: duckdb.DuckDBPyConnection,
    cohort: dict[str, object],
) -> dict[str, int | float]:
    minimum_badge = max(
        CORE_ECONOMY_REFERENCE_MINIMUM_BADGE,
        integer(cohort["minimum_badge"]),
    )
    maximum_badge = integer(cohort["maximum_badge"])
    if minimum_badge > maximum_badge:
        raise RuntimeError("cohort does not include the Oracle I+ economy reference")
    row = con.execute(
        """
        WITH reference_players AS (
            SELECT p.match_id, p.player_slot, p.duration_s, p.final_net_worth
            FROM player_matches p
            JOIN match_folds f USING (match_id)
            WHERE p.average_badge BETWEEN ? AND ?
              AND f.fold IN ('train', 'validation')
        ), final_inventories AS (
            SELECT p.match_id, p.player_slot,
                   count(*) FILTER (WHERE sold_time = 0) AS item_count,
                   sum(cost) FILTER (WHERE sold_time = 0) AS inventory_cost
            FROM purchases p
            JOIN match_folds f USING (match_id)
            WHERE p.average_badge BETWEEN ? AND ?
              AND f.fold IN ('train', 'validation')
            GROUP BY p.match_id, p.player_slot
        ), observed AS (
            SELECT players.match_id, players.player_slot, players.duration_s,
                   players.final_net_worth,
                   coalesce(inventory.item_count, 0) AS item_count,
                   coalesce(inventory.inventory_cost, 0) AS inventory_cost
            FROM reference_players AS players
            LEFT JOIN final_inventories AS inventory
              USING (match_id, player_slot)
        )
        SELECT count(DISTINCT match_id), count(*), avg(duration_s),
               median(duration_s), avg(final_net_worth), median(final_net_worth),
               median(item_count), median(inventory_cost)
        FROM observed
        """,
        [minimum_badge, maximum_badge, minimum_badge, maximum_badge],
    ).fetchone()
    if row is None or row[6] is None or row[7] is None or int(row[6]) <= 0:
        raise RuntimeError("Oracle I+ economy reference is empty")
    median_inventory_items = int(row[6])
    median_inventory_cost = int(row[7])
    reserved_item_equivalents = min(MAX_FLEX_SLOTS, median_inventory_items - 1)
    target_cost = round(
        median_inventory_cost
        * (median_inventory_items - reserved_item_equivalents)
        / median_inventory_items
    )
    return {
        "minimum_badge": minimum_badge,
        "maximum_badge": maximum_badge,
        "matches": int(row[0]),
        "player_matches": int(row[1]),
        "mean_duration_s": float(row[2]),
        "median_duration_s": float(row[3]),
        "mean_final_net_worth": float(row[4]),
        "median_final_net_worth": float(row[5]),
        "median_final_inventory_items": median_inventory_items,
        "median_final_inventory_cost": median_inventory_cost,
        "reserved_situational_item_equivalents": reserved_item_equivalents,
        "target_core_cost": target_cost,
    }


def _purchase_priorities(
    hero_metrics: pl.DataFrame,
) -> dict[int, tuple[float, float, int]]:
    return {
        item_id: (
            float(row.get("selection_median_valid_buy_net_worth") or float("inf")),
            float(row.get("selection_median_buy_time_s") or float("inf")),
            item_id,
        )
        for row in hero_metrics.iter_rows(named=True)
        for item_id in (int(row["item_id"]),)
    }


def _purchase_window_bounds(
    hero_metrics: pl.DataFrame,
) -> dict[int, tuple[float, float]]:
    result: dict[int, tuple[float, float]] = {}
    for row in hero_metrics.iter_rows(named=True):
        lower = row.get("selection_buy_nw_q25")
        upper = row.get("selection_buy_nw_q75")
        training_lower = row.get("training_buy_nw_q25")
        training_upper = row.get("training_buy_nw_q75")
        validation_lower = row.get("validation_buy_nw_q25")
        validation_upper = row.get("validation_buy_nw_q75")
        reliable = (
            float(row.get("selection_valid_buy_nw_observations") or 0)
            / max(float(row.get("selection_adopter_matches") or 0), 1.0)
            >= MINIMUM_PURCHASE_WINDOW_COVERAGE
            and int(row.get("training_valid_buy_nw_observations") or 0)
            >= MINIMUM_PURCHASE_WINDOW_OBSERVATIONS
            and int(row.get("validation_valid_buy_nw_observations") or 0)
            >= MINIMUM_PURCHASE_WINDOW_OBSERVATIONS
            and training_lower is not None
            and training_upper is not None
            and validation_lower is not None
            and validation_upper is not None
            and max(float(training_lower), float(validation_lower))
            <= min(float(training_upper), float(validation_upper))
        )
        if reliable and lower is not None and upper is not None:
            result[int(row["item_id"])] = (float(lower), float(upper))
    return result


def _qualified_tier_rows(
    rows: dict[int, dict[str, object]],
    tier: int,
    excluded: set[int],
    *,
    graph: ItemGraph,
    visible_higher_tier_ids: set[int],
    fold_eligible_matches: dict[str, int],
    rejection_counts: Counter[str],
) -> list[dict[str, object]]:
    qualified: list[dict[str, object]] = []
    for item_id, row in rows.items():
        if integer(row["tier"]) != tier or item_id in excluded:
            continue
        training_support = integer(row["training_adopter_matches"])
        validation_support = integer(row["validation_adopter_matches"])
        training_adoption = training_support / fold_eligible_matches["train"]
        validation_adoption = validation_support / fold_eligible_matches["validation"]
        upgrades = set(graph.children[item_id])
        gates = {
            "training_support": training_support >= MINIMUM_CORE_SUPPORT,
            "validation_support": validation_support >= MINIMUM_CORE_SUPPORT,
            "training_adoption": training_adoption >= MINIMUM_TIER_ADOPTION,
            "validation_adoption": validation_adoption >= MINIMUM_TIER_ADOPTION,
            "adoption_stability": abs(training_adoption - validation_adoption)
            <= MAXIMUM_TIER_ADOPTION_DRIFT,
            "upgrade_visibility": not upgrades
            or bool(upgrades & visible_higher_tier_ids),
        }
        if all(gates.values()):
            qualified.append(row)
        else:
            rejection_counts.update(
                name for name, passed in gates.items() if not passed
            )
    return qualified


def _selected_tier_rows(
    qualified: list[dict[str, object]],
    reliable_window_bounds: dict[int, tuple[float, float]],
    fold_eligible_matches: dict[str, int],
) -> list[dict[str, object]]:
    selected = sorted(
        qualified,
        key=lambda row: (
            -integer(row["training_adopter_matches"]) / fold_eligible_matches["train"],
            -integer(row["training_adopter_matches"]),
            integer(row["item_id"]),
        ),
    )[:TIER_ITEM_COUNT]
    return sorted(
        selected,
        key=lambda row: (
            integer(row["item_id"]) not in reliable_window_bounds,
            (
                number(row.get("selection_median_valid_buy_net_worth") or 0.0)
                if integer(row["item_id"]) in reliable_window_bounds
                else float("inf")
            ),
            (
                number(row.get("selection_median_buy_time_s") or 0.0)
                if integer(row["item_id"]) in reliable_window_bounds
                else float("inf")
            ),
            integer(row["item_id"]),
        ),
    )


def _tier_policy(
    hero_id: int,
    hero_metrics: pl.DataFrame,
    core_item_ids: tuple[int, ...],
    optional_core_item_ids: frozenset[int],
    graph: ItemGraph,
    fold_eligible_matches: dict[str, int],
) -> dict[str, object]:
    rows = {int(row["item_id"]): row for row in hero_metrics.iter_rows(named=True)}
    excluded = set(core_item_ids) | set(optional_core_item_ids)
    visible_higher_tier_ids = set(core_item_ids) | set(optional_core_item_ids)
    reliable_window_bounds = _purchase_window_bounds(hero_metrics)
    item_ids_by_tier: dict[str, list[int]] = {}
    rejection_counts: Counter[str] = Counter()

    for tier in range(4, 0, -1):
        qualified = _qualified_tier_rows(
            rows,
            tier,
            excluded,
            graph=graph,
            visible_higher_tier_ids=visible_higher_tier_ids,
            fold_eligible_matches=fold_eligible_matches,
            rejection_counts=rejection_counts,
        )
        selected = _selected_tier_rows(
            qualified,
            reliable_window_bounds,
            fold_eligible_matches,
        )
        if not selected:
            raise UnsupportedBuildPathError(
                f"hero {hero_id} has no supported non-CORE Tier {tier} item"
            )
        selected_ids = [integer(row["item_id"]) for row in selected]
        item_ids_by_tier[str(tier)] = selected_ids
        visible_higher_tier_ids.update(selected_ids)
    return {
        "version": TIER_POLICY_VERSION,
        "item_ids_by_tier": item_ids_by_tier,
        "selection": {
            "primary_fold": "train",
            "validation_fold": "validation",
            "test_usage": "audit_only",
            "minimum_fold_support": MINIMUM_CORE_SUPPORT,
            "minimum_fold_adoption": MINIMUM_TIER_ADOPTION,
            "maximum_adoption_rate_drift": MAXIMUM_TIER_ADOPTION_DRIFT,
            "maximum_items_per_tier": TIER_ITEM_COUNT,
            "rejection_counts": dict(sorted(rejection_counts.items())),
        },
    }


def _path_label(
    con: duckdb.DuckDBPyConnection,
    path: DiscoveredBuildPath,
    assets_by_id: dict[int, dict[str, object]],
) -> str:
    members = pl.DataFrame({
        "match_id": [identity[0] for identity in path.member_ids],
        "player_slot": [identity[1] for identity in path.member_ids],
    })
    con.register("_build_path_members", members)
    try:
        row = con.execute(
            """
            SELECT imbued_ability_id, count(DISTINCT (match_id, player_slot)) AS players
            FROM purchases p
            JOIN _build_path_members m USING (match_id, player_slot)
            JOIN match_folds f USING (match_id)
            WHERE f.fold = 'train' AND imbued_ability_id > 0
            GROUP BY imbued_ability_id
            ORDER BY players DESC, imbued_ability_id
            LIMIT 1
            """
        ).fetchone()
    finally:
        con.unregister("_build_path_members")
    training_members = path.fold_support.get("train", 0)
    if row is not None and training_members and int(row[1]) / training_members >= 0.5:
        ability = assets_by_id.get(int(row[0]), {})
        name = ability.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    slots = [
        str(assets_by_id.get(item_id, {}).get("item_slot_type") or "").casefold()
        for item_id in path.signature_item_ids
    ]
    slot = Counter(value for value in slots if value).most_common(1)
    if slot:
        return f"{slot[0][0].title()} Core"
    if path.signature_item_ids:
        item = assets_by_id.get(path.signature_item_ids[0], {})
        name = item.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return DEFAULT_BUILD_PATH_LABEL
