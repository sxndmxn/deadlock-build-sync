from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import duckdb
    import polars as pl


def state_overlap_diagnostics(
    con: duckdb.DuckDBPyConnection,
    *,
    hero_id: int | None = None,
) -> pl.DataFrame:
    """Measure item support in comparable observed states."""
    selection = (
        ""
        if hero_id is None
        else f"WHERE hero_id = {hero_id} AND fold IN ('train', 'validation')"
    )
    return con.sql(
        f"""
        WITH decisions AS (
            SELECT *,
                   CASE WHEN own_net_worth_at_buy IS NULL THEN -1
                        ELSE least(12, floor(own_net_worth_at_buy / 5000))::INTEGER
                   END AS own_nw_band,
                   CASE WHEN team_net_worth_lead IS NULL THEN -99
                        ELSE greatest(
                            -8, least(8, floor(team_net_worth_lead / 5000))
                        )::INTEGER
                   END AS lead_band
            FROM decision_opportunities
            {selection}
        ), reference_states AS (
            SELECT hero_id, tier, phase, own_nw_band, lead_band,
                   count(*) AS reference_observations
            FROM decisions GROUP BY ALL
        ), reference_totals AS (
            SELECT hero_id, tier, sum(reference_observations) AS reference_total
            FROM reference_states GROUP BY ALL
        ), item_states AS (
            SELECT hero_id, tier, item_id, phase, own_nw_band, lead_band,
                   count(*) AS item_observations
            FROM decisions GROUP BY ALL
        ), overlap AS (
            SELECT i.*, r.reference_observations, t.reference_total,
                   sum(r.reference_observations) OVER (
                       PARTITION BY i.hero_id, i.tier, i.item_id
                   ) AS covered_reference
            FROM item_states i
            JOIN reference_states r
              USING (hero_id, tier, phase, own_nw_band, lead_band)
            JOIN reference_totals t USING (hero_id, tier)
        )
        SELECT hero_id, tier, item_id,
               sum(item_observations) AS item_observations,
               any_value(covered_reference) / any_value(reference_total)
                   AS state_coverage,
               1.0 / sum(
                   pow(reference_observations / covered_reference, 2)
                   / item_observations
               ) AS effective_support,
               effective_support / sum(item_observations) AS effective_support_share,
               max(
                   (reference_observations / covered_reference) / item_observations
               ) AS maximum_individual_weight
        FROM overlap GROUP BY hero_id, tier, item_id
        """
    ).pl()
