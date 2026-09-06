from __future__ import annotations

import math
from typing import TYPE_CHECKING, cast

import numpy as np
import polars as pl
from deadlock_build_sync.offline.api import read_json
from deadlock_build_sync.offline.config import RunPaths
from deadlock_build_sync.value_validation import (
    integer,
    object_dict,
    object_list,
    object_rows,
)
from scipy.stats import spearmanr

if TYPE_CHECKING:
    import duckdb


def _duration_profiles(paths: RunPaths) -> pl.DataFrame:
    labels = {
        "under-25m": "<25m",
        "25-30m": "25-30m",
        "30-35m": "30-35m",
        "35-40m": "35-40m",
        "40-45m": "40-45m",
        "45-50m": "45-50m",
        "50m-plus": "50m+",
    }
    rows: list[dict[str, object]] = []
    for path in sorted(paths.api.glob("hero-duration-*.json")):
        key = path.stem.removeprefix("hero-duration-")
        source_rows = object_rows(read_json(path))
        if source_rows is None:
            raise TypeError(f"{path} is not an array of objects")
        for row in source_rows:
            matches = integer(row.get("matches"), default=0)
            wins = integer(row.get("wins"), default=0)
            if matches < 20 or not isinstance(row.get("hero_id"), int):
                continue
            rows.append({
                "hero_id": integer(row["hero_id"]),
                "duration_bucket": labels.get(key, key),
                "wins": wins,
                "matches": matches,
                "ending_outcome_rate": wins / matches,
            })
    return pl.DataFrame(rows) if rows else pl.DataFrame()


def _match_bootstrap_intervals(metrics: pl.DataFrame) -> pl.DataFrame:
    rng = np.random.default_rng(20260809)
    rows: list[dict[str, object]] = []
    top = (
        metrics
        .sort(
            ["hero_id", "tier", "adoption_rate"],
            descending=[False, False, True],
        )
        .group_by(["hero_id", "tier"], maintain_order=True)
        .head(10)
    )
    for row in top.to_dicts():
        observations = int(row["adopter_matches"])
        probability = float(row["raw_outcome_rate"])
        # A hero-item has at most one row per match, so resampling match clusters is
        # exactly a binomial resample of these binary outcomes.
        samples = rng.binomial(observations, probability, size=500) / observations
        rows.append({
            "hero_id": int(row["hero_id"]),
            "tier": int(row["tier"]),
            "item_id": int(row["item_id"]),
            "observations": observations,
            "bootstrap_lower": float(np.quantile(samples, 0.025)),
            "bootstrap_median": float(np.quantile(samples, 0.5)),
            "bootstrap_upper": float(np.quantile(samples, 0.975)),
            "bootstrap_replicates": 500,
        })
    return pl.DataFrame(rows)


def _api_audit(
    paths: RunPaths, con: duckdb.DuckDBPyConnection
) -> tuple[pl.DataFrame, pl.DataFrame]:
    raw_events = con.sql(
        """
        SELECT hero_id, item_id, count(*) AS raw_purchase_events,
               count(*) FILTER (WHERE item_purchase_ordinal = 1) AS raw_first_purchase_matches
        FROM purchases GROUP BY hero_id, item_id
        """
    ).pl()
    api_rows: list[dict[str, object]] = []
    flow_rows: list[dict[str, object]] = []
    for path in sorted(paths.api.glob("hero-*-item-stats.json")):
        hero_id = int(path.name.split("-")[1])
        rows = object_rows(read_json(path))
        if rows is None:
            raise TypeError(f"{path} is not an array of objects")
        api_rows.extend(
            {
                "hero_id": hero_id,
                "item_id": integer(row["item_id"]),
                "api_purchase_events": integer(row["matches"]),
                "api_unique_accounts": integer(row["players"]),
                "api_outcome_rate": integer(row["wins"])
                / max(1, integer(row["matches"])),
                "api_avg_buy_time_s": row.get("avg_buy_time_s"),
            }
            for row in rows
        )
    for path in sorted(paths.api.glob("hero-*-item-flow-stats.json")):
        hero_id = int(path.name.split("-")[1])
        payload = object_dict(read_json(path))
        if payload is None:
            raise TypeError(f"{path} is not an object")
        rows = object_rows(payload.get("nodes")) or []
        flow_rows.extend(
            {
                "hero_id": hero_id,
                "item_id": integer(row["item_id"]),
                "phase": integer(row["column"]),
                "api_flow_matches": integer(row["matches"]),
                "api_flow_player_matches": integer(row["players"]),
                "api_adjusted_win_rate": row["adjusted_win_rate"],
                "api_avg_net_worth_at_buy": row["avg_net_worth_at_buy"],
            }
            for row in rows
        )
    api_frame = pl.DataFrame(api_rows) if api_rows else pl.DataFrame()
    if not api_frame.is_empty():
        hero_accounts = con.sql(
            "SELECT hero_id, unique_accounts AS hero_unique_accounts "
            "FROM hero_account_counts"
        ).pl()
        api_frame = api_frame.join(
            hero_accounts, on="hero_id", how="left"
        ).with_columns(
            (pl.col("api_unique_accounts") / pl.col("hero_unique_accounts")).alias(
                "api_account_breadth"
            )
        )
    event_audit = (
        raw_events.join(api_frame, on=["hero_id", "item_id"], how="inner")
        if not api_frame.is_empty()
        else raw_events
    )
    flow_frame = pl.DataFrame(flow_rows) if flow_rows else pl.DataFrame()
    raw_flow = con.sql(
        """
        SELECT hero_id, item_id, phase,
               count(*) AS raw_first_purchase_matches,
               avg(own_net_worth_at_buy) AS raw_valid_avg_net_worth_at_buy,
               median(own_net_worth_at_buy) AS raw_valid_median_net_worth_at_buy,
               count(own_net_worth_at_buy) / count(*) AS valid_state_share
        FROM first_purchases GROUP BY ALL
        """
    ).pl()
    flow_audit = (
        raw_flow.join(flow_frame, on=["hero_id", "item_id", "phase"], how="inner")
        if not flow_frame.is_empty()
        else raw_flow
    )
    return event_audit, flow_audit


def _account_breadth_stability(
    metrics: pl.DataFrame, api_events: pl.DataFrame
) -> pl.DataFrame:
    joined = (
        metrics
        .select("hero_id", "tier", "item_id", "adoption_rate")
        .join(
            api_events.select("hero_id", "item_id", "api_account_breadth"),
            on=["hero_id", "item_id"],
            how="inner",
        )
        .drop_nulls()
    )
    rows: list[dict[str, object]] = []
    for key, group in joined.group_by(["hero_id", "tier"]):
        if group.height < 3:
            continue
        correlation = spearmanr(
            group["adoption_rate"].to_numpy(),
            group["api_account_breadth"].to_numpy(),
        ).statistic
        adoption_top = set(
            group.sort("adoption_rate", descending=True).head(10)["item_id"].to_list()
        )
        breadth_top = set(
            group
            .sort("api_account_breadth", descending=True)
            .head(10)["item_id"]
            .to_list()
        )
        union = adoption_top | breadth_top
        rows.append({
            "hero_id": int(key[0]),
            "tier": int(key[1]),
            "shared_items": group.height,
            "spearman": float(correlation) if math.isfinite(correlation) else None,
            "top10_jaccard": len(adoption_top & breadth_top) / len(union),
        })
    return pl.DataFrame(rows)


def _effective_property_value(prop: dict[str, object]) -> bool:
    value = prop.get("value")
    if value is None:
        return False
    normalized = str(value).strip().lower()
    return normalized not in {"", "0", "0.0", "-1", "-1.0", "-2", "-2.0", "false"}


def _item_mechanics_rows(items: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "item_id": integer(item["id"]),
            "item_name": item.get("name"),
            "tier": item.get("item_tier"),
            "slot": item.get("item_slot_type"),
            "cost": item.get("cost"),
            "active": bool(item.get("is_active_item")),
            "has_properties": bool(item.get("properties")),
            "has_components": bool(item.get("component_items")),
            "has_description": bool(item.get("description")),
        }
        for item in items
    ]


type _ScalingSignals = tuple[list[str], set[str], set[str], list[float]]
type _AbilityProperty = dict[str, object]
type _ScaleFunction = dict[str, object]
type _HeroItemReferences = dict[str, object]


def _effective_scale_function(prop: object) -> _ScaleFunction | None:
    if not isinstance(prop, dict):
        return None
    property_data = cast("_AbilityProperty", prop)
    if not _effective_property_value(property_data):
        return None
    scale = property_data.get("scale_function")
    if not isinstance(scale, dict):
        return None
    return cast("_ScaleFunction", scale)


def _ability_scaling_signals(ability: dict[str, object]) -> _ScalingSignals:
    properties = object_dict(ability.get("properties")) or {}
    scaled_properties: list[str] = []
    scale_functions: set[str] = set()
    scale_types: set[str] = set()
    spirit_coefficients: list[float] = []
    for property_name, prop in properties.items():
        scale = _effective_scale_function(prop)
        if scale is None:
            continue
        scaled_properties.append(str(property_name))
        class_value = str(scale.get("class_name") or "")
        if class_value:
            scale_functions.add(class_value)
        specific = scale.get("specific_stat_scale_type")
        if specific:
            scale_types.add(str(specific))
        scale_types.update(
            str(stat) for stat in object_list(scale.get("scaling_stats")) or []
        )
        coefficient = scale.get("stat_scale")
        if "tech_damage" in class_value and isinstance(coefficient, int | float):
            spirit_coefficients.append(float(coefficient))
    return scaled_properties, scale_functions, scale_types, spirit_coefficients


def _ability_mechanics_row(
    hero: dict[str, object],
    slot: int,
    class_name: object,
    ability: dict[str, object],
) -> dict[str, object]:
    scaled, functions, scale_types, spirit_coefficients = _ability_scaling_signals(
        ability
    )
    description = object_dict(ability.get("description")) or {}
    all_scale_types = (*functions, *scale_types)
    return {
        "hero_id": integer(hero["id"]),
        "hero_name": hero.get("name"),
        "ability_slot": slot,
        "ability_class": class_name,
        "ability_name": ability.get("name"),
        "ability_quip": description.get("quip")
        if isinstance(description, dict)
        else None,
        "scaled_property_count": len(scaled),
        "scaled_properties": " | ".join(sorted(scaled)),
        "scale_functions": " | ".join(sorted(functions)),
        "specific_scale_types": " | ".join(sorted(scale_types)),
        "spirit_damage_coefficients": " | ".join(
            f"{value:g}" for value in sorted(spirit_coefficients)
        ),
        "has_spirit_damage_scaling": bool(spirit_coefficients),
        "has_duration_scaling": any(
            "duration" in value.lower() for value in all_scale_types
        ),
        "has_range_or_radius_scaling": any(
            token in value.lower()
            for value in all_scale_types
            for token in ("range", "radius")
        ),
        "has_cooldown_or_recharge_scaling": any(
            token in value.lower()
            for value in all_scale_types
            for token in ("cooldown", "recharge")
        ),
    }


def _audit_hero_mechanics(
    hero: dict[str, object],
    by_class: dict[str, dict[str, object]],
) -> tuple[dict[str, object], list[dict[str, object]]]:
    raw_references = hero.get("items")
    references = cast(
        "_HeroItemReferences",
        object_dict(raw_references) or {},
    )
    abilities = [references.get(f"signature{slot}") for slot in range(1, 5)]
    resolved = [by_class.get(str(class_name), {}) for class_name in abilities]
    ability_rows = [
        _ability_mechanics_row(hero, slot, class_name, ability)
        for slot, (class_name, ability) in enumerate(
            zip(abilities, resolved, strict=True), start=1
        )
    ]
    hero_row = {
        "hero_id": integer(hero["id"]),
        "hero_name": hero.get("name"),
        "signature_abilities": sum(bool(value) for value in abilities),
        "resolved_abilities": sum(bool(value) for value in resolved),
        "abilities_with_scaling": sum(
            bool(row["scaled_property_count"]) for row in ability_rows
        ),
    }
    return hero_row, ability_rows


def _mechanics_audit(
    paths: RunPaths,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    items = object_rows(read_json(paths.raw / "items.json"))
    all_assets = object_rows(read_json(paths.raw / "items-all.json"))
    heroes = object_rows(read_json(paths.raw / "heroes.json"))
    if items is None or all_assets is None or heroes is None:
        raise TypeError("mechanics assets are not arrays of objects")
    by_class = {
        str(asset.get("class_name")): asset
        for asset in all_assets
        if asset.get("class_name")
    }
    item_rows = _item_mechanics_rows(items)
    hero_rows: list[dict[str, object]] = []
    ability_rows: list[dict[str, object]] = []
    for hero in heroes:
        hero_row, hero_abilities = _audit_hero_mechanics(hero, by_class)
        hero_rows.append(hero_row)
        ability_rows.extend(hero_abilities)
    return (
        pl.DataFrame(item_rows),
        pl.DataFrame(hero_rows),
        pl.DataFrame(ability_rows),
    )
