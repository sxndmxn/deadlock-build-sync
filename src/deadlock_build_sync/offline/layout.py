from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl

from .api import read_json, write_json
from .config import RunPaths

CORE_ITEM_COUNT = 8
TIER_ITEM_COUNT = 10
MINIMUM_TIER_SUPPORT = 20


def _seconds_label(value: float | None) -> str:
    if value is None:
        return "unavailable"
    seconds = round(float(value))
    minutes, remainder = divmod(seconds, 60)
    return f"{minutes}:{remainder:02d}"


def _souls_range(lower: float | None, upper: float | None) -> str:
    if lower is None or upper is None:
        return "unavailable"
    return f"{float(lower) / 1000:.1f}k–{float(upper) / 1000:.1f}k"


def _item(row: dict[str, Any], *, core: bool) -> dict[str, Any]:
    return {
        "item_id": int(row["item_id"]),
        "item": str(row["item_name"]),
        "tier": int(row["tier"]),
        "core": core,
        "purchase_adoption": float(row["purchase_adoption"]),
        "final_inventory_adoption": float(row["final_inventory_adoption"]),
        "observed_outcome_rate": float(row["outcome_rate"]),
        "buyer_matches": int(row["buyer_matches"]),
        "median_buy_time_s": float(row["median_buy_time_s"]),
        "median_buy_net_worth": (
            float(row["median_buy_net_worth"])
            if row.get("median_buy_net_worth") is not None
            else None
        ),
        "buy_nw_q25": (
            float(row["buy_nw_q25"]) if row.get("buy_nw_q25") is not None else None
        ),
        "buy_nw_q75": (
            float(row["buy_nw_q75"]) if row.get("buy_nw_q75") is not None else None
        ),
        "valid_buy_nw_share": float(row.get("valid_buy_nw_share") or 0.0),
    }


def _net_worth_order(item: dict[str, Any]) -> tuple[bool, float, float, int]:
    median = item["median_buy_net_worth"]
    return (
        median is None,
        float(median) if median is not None else float("inf"),
        float(item["median_buy_time_s"]),
        int(item["item_id"]),
    )


def create_build_layout(
    late_game: dict[str, Any],
    items: pl.DataFrame,
    *,
    hero_name: str,
    tier_item_count: int = TIER_ITEM_COUNT,
) -> dict[str, Any]:
    """Create the five-row shop layout from frozen late-game evidence."""
    if tier_item_count <= 0:
        raise ValueError("tier item count must be positive")
    core = late_game.get("most_common_eight_item_core")
    if not isinstance(core, dict) or not isinstance(core.get("item_ids"), list):
        raise ValueError("late-game result has no coherent eight-item core")
    core_ids = [int(item_id) for item_id in core["item_ids"]]
    if len(core_ids) != CORE_ITEM_COUNT or len(set(core_ids)) != CORE_ITEM_COUNT:
        raise ValueError("core must contain exactly eight distinct items")

    rows_by_id = {int(row["item_id"]): row for row in items.iter_rows(named=True)}
    missing_core = [item_id for item_id in core_ids if item_id not in rows_by_id]
    if missing_core:
        raise ValueError(f"core item metrics are missing: {missing_core}")

    core_items = sorted(
        (_item(rows_by_id[item_id], core=True) for item_id in core_ids),
        key=lambda row: (float(row["median_buy_time_s"]), int(row["item_id"])),
    )
    rows: list[dict[str, Any]] = [
        {
            "name": "CORE ITEMS",
            "optional": False,
            "purpose": "Coherent eight-item end-state targets for the selected archetype.",
            "sort": "observed median acquisition time",
            "items": core_items,
        }
    ]
    for tier in range(1, 5):
        tier_shortlist = (
            items
            .filter(
                (pl.col("tier") == tier)
                & (~pl.col("item_id").is_in(core_ids))
                & (pl.col("buyer_matches") >= MINIMUM_TIER_SUPPORT)
            )
            .sort(
                ["purchase_adoption", "buyer_matches", "item_id"],
                descending=[True, True, False],
            )
            .head(tier_item_count)
        )
        if tier_shortlist.is_empty():
            raise ValueError(f"Tier {tier} has no supported non-CORE items")
        tier_items = sorted(
            (_item(row, core=False) for row in tier_shortlist.iter_rows(named=True)),
            key=_net_worth_order,
        )
        rows.append({
            "name": f"TIER {tier}",
            "optional": True,
            "purpose": "Supported, non-CORE price-tier reference menu.",
            "selection": "up to ten by true player-match purchase adoption",
            "sort": "median valid pre-purchase net worth; missing windows last",
            "items": tier_items,
        })

    cohort = late_game.get("cohort")
    if not isinstance(cohort, dict):
        raise ValueError("late-game result has no cohort summary")
    return {
        "schema_version": 1,
        "hero_id": int(late_game["hero_id"]),
        "hero": hero_name,
        "minimum_final_net_worth": int(late_game["minimum_final_net_worth"]),
        "cohort": cohort,
        "core_joint_matches": int(core["matches"]),
        "core_joint_share": float(core["share"]),
        "rows": rows,
        "interpretation": {
            "adoption": "unique hero-player-matches purchasing the item divided by eligible hero-player-matches",
            "outcome": "observed outcome among item buyers; descriptive association only",
            "tier_order": "select by adoption, then order left-to-right by valid pre-purchase net-worth window",
            "duplication": "CORE and optional tier menus are disjoint",
            "queue": "only CORE ITEMS is the default queue; tier rows are reference menus",
        },
    }


def render_build_layout_markdown(layout: dict[str, Any]) -> str:
    """Render a reviewable Markdown preview of a five-row build layout."""
    cohort = layout["cohort"]
    minimum_net_worth = int(layout["minimum_final_net_worth"])
    if minimum_net_worth:
        title_scope = f"{minimum_net_worth // 1000}k+"
        cohort_filter = f"At least {minimum_net_worth:,} final souls"
        cohort_caution = (
            "Filtering on final net worth selects long, high-economy games and correlates with\n"
            "> winning. Do not compare these outcome rates with an unfiltered hero baseline as an\n"
            "> item effect."
        )
    else:
        title_scope = "all-game"
        cohort_filter = "All eligible games"
        cohort_caution = (
            "This is an observational all-game cohort. Item-buyer outcomes still describe\n"
            "> associations rather than item effects."
        )
    shop_rows = []
    for row in layout["rows"]:
        item_names = " → ".join(
            f"**{item['item']}**" if item["core"] else str(item["item"])
            for item in row["items"]
        )
        shop_rows.append(f"| **{row['name']}** | {item_names} |")

    evidence_sections: list[str] = []
    for row in layout["rows"]:
        evidence_rows = []
        for position, item in enumerate(row["items"], start=1):
            evidence_rows.append(
                "| "
                + " | ".join((
                    str(position),
                    f"**{item['item']}**" if item["core"] else item["item"],
                    str(item["tier"]),
                    f"{item['purchase_adoption']:.1%}",
                    f"{item['observed_outcome_rate']:.1%}",
                    f"{item['buyer_matches']:,}",
                    _seconds_label(item["median_buy_time_s"]),
                    (
                        f"{item['median_buy_net_worth'] / 1000:.1f}k"
                        if item["median_buy_net_worth"] is not None
                        else "unavailable"
                    ),
                    _souls_range(item["buy_nw_q25"], item["buy_nw_q75"]),
                    f"{item['valid_buy_nw_share']:.0%}",
                ))
                + " |"
            )
        evidence_sections.append(
            f"### {row['name']}\n\n"
            f"*Order: {row['sort']}.*\n\n"
            "| # | Item | Tier | Purchase adoption | Observed outcome | Buyers | Median time | Median buyer NW | Buyer NW middle 50% | NW coverage |\n"
            "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|\n"
            + "\n".join(evidence_rows)
        )

    return f"""---
title: "{layout["hero"]} {title_scope} build layout"
hero_id: {layout["hero_id"]}
minimum_final_net_worth: {layout["minimum_final_net_worth"]}
schema_version: {layout["schema_version"]}
---

# {layout["hero"]} — {title_scope} souls build layout

> [!IMPORTANT]
> This is an evidence preview, not a causal claim. Adoption is the ranking signal.
> “Observed outcome” is the buyer cohort's descriptive outcome rate and is never the
> item selection or sort key. Tier candidates are selected by adoption and placed
> left-to-right by valid pre-purchase net-worth windows.

## Shop layout

| Row | Items, left to right |
|---|---|
{chr(10).join(shop_rows)}

The `CORE ITEMS` row is the only default queue. Tier rows are disjoint, optional
reference menus; unsupported choices are omitted instead of added as filler.

## Cohort

- **Hero-player-matches:** {int(cohort["player_matches"]):,}
- **Cohort filter:** {cohort_filter}
- **Median final net worth:** {float(cohort["median_final_net_worth"]):,.0f} souls
- **Median duration:** {_seconds_label(cohort["median_duration_s"])}
- **Observed cohort outcome:** {float(cohort["outcome_rate"]):.1%}
- **Eight-item core joint support:** {int(layout["core_joint_matches"]):,} matches ({float(layout["core_joint_share"]):.1%})

> [!CAUTION]
> {cohort_caution}
>
> Early net-worth coverage can be sparse. The table reports coverage explicitly; no
> missing opening state is replaced with final net worth.

## Row evidence

{(chr(10) * 2).join(evidence_sections)}

## Rendering requirements demonstrated

1. Emit exactly five rows in this order: `CORE ITEMS`, `TIER 1`, `TIER 2`, `TIER 3`, `TIER 4`.
2. Emit exactly eight coherent core targets; never reduce the core to one item per tier.
3. Select up to ten non-CORE candidates per tier with at least 20 buyer matches, then
   order them left-to-right by valid pre-purchase net-worth windows.
4. Display observed outcome and support, but never sort by observed outcome.
5. Keep consumed components in their purchase tier even when final ownership is low.
6. Keep CORE and every optional tier menu disjoint.
"""


def write_build_layout(
    paths: RunPaths,
    *,
    hero_id: int,
    hero_name: str,
    minimum_net_worth: int,
) -> tuple[Path, Path]:
    stem = f"late_game_hero_{hero_id}_{minimum_net_worth}"
    late_game = read_json(paths.tables / f"{stem}.json")
    items = pl.read_csv(paths.tables / f"{stem}_items.csv")
    layout = create_build_layout(late_game, items, hero_name=hero_name)
    output_dir = paths.run / "builds"
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = hero_name.casefold().replace(" ", "-")
    cohort_slug = f"{minimum_net_worth}-plus" if minimum_net_worth else "all-games"
    output_stem = output_dir / f"{slug}-{cohort_slug}"
    json_path = output_stem.with_suffix(".json")
    markdown_path = output_stem.with_suffix(".md")
    write_json(json_path, layout)
    markdown_path.write_text(render_build_layout_markdown(layout), encoding="utf-8")
    return json_path, markdown_path
