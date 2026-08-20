from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

import duckdb

from .config import DUCKLAKE_URL, Cohort, RunPaths

_REMOTE_QUERY_ATTEMPTS = 4
_RETRYABLE_REMOTE_ERRORS = (
    "No magic bytes found at end of file",
    "HTTP GET error",
    "Connection error",
)


def _sql_timestamp(value: Any) -> str:
    return value.isoformat().replace("+00:00", "+00")


def _cohort_where(cohort: Cohort) -> str:
    return f"""
        match_mode = '{cohort.match_mode}'
        AND game_mode = '{cohort.game_mode}'
        AND start_time >= TIMESTAMPTZ '{_sql_timestamp(cohort.since)}'
        AND start_time + duration_s * INTERVAL '1 second'
            <= TIMESTAMPTZ '{_sql_timestamp(cohort.resolved_as_of())}'
        AND average_badge BETWEEN {cohort.minimum_badge} AND {cohort.maximum_badge}
    """


def _eligible_matches_query(
    cohort: Cohort,
    *,
    source: str = "remote.main.match_player",
) -> str:
    """Return the whole-match admission query for a trusted table reference."""
    return f"""
        SELECT match_id
        FROM {source}
        WHERE {_cohort_where(cohort)}
        GROUP BY match_id
        HAVING count(*) = 12
           AND count(DISTINCT player_slot) = 12
           AND count(*) FILTER (WHERE team = 'Team0') = 6
           AND count(*) FILTER (WHERE team = 'Team1') = 6
           AND bool_and(rewards_eligible)
           AND bool_and(player_match_outcome IN ('Win', 'Loss'))
           AND count(*) FILTER (WHERE player_match_outcome = 'Win') = 6
           AND count(*) FILTER (WHERE player_match_outcome = 'Loss') = 6
    """


def _connect(paths: RunPaths) -> duckdb.DuckDBPyConnection:
    database = paths.raw / "analysis.duckdb"
    con = duckdb.connect(str(database))
    con.execute("SET threads = 8")
    con.execute("SET memory_limit = '12GB'")
    con.execute(f"SET temp_directory = '{paths.raw / 'duckdb-tmp'}'")
    con.execute("INSTALL ducklake; LOAD ducklake; INSTALL httpfs; LOAD httpfs")
    con.execute(
        """
        CREATE OR REPLACE SECRET deadlock_s3 (
            TYPE S3,
            KEY_ID '',
            SECRET '',
            ENDPOINT 's3-cache.deadlock-api.com',
            URL_STYLE 'path',
            USE_SSL true
        )
        """
    )
    con.execute(f"ATTACH '{DUCKLAKE_URL}' AS remote (READ_ONLY)")
    return con


def _load_item_assets(con: duckdb.DuckDBPyConnection, path: Path) -> None:
    items = json.loads(path.read_text(encoding="utf-8"))
    rows = [
        (
            int(item["id"]),
            str(item.get("name") or f"Item {item['id']}"),
            str(item.get("class_name") or ""),
            int(item["item_tier"]),
            int(item.get("cost") or 0),
            str(item.get("item_slot_type") or "unknown").casefold(),
            bool(item.get("is_active_item")),
            bool(item.get("is_unique", True)),
            json.dumps(item.get("component_items") or []),
        )
        for item in items
    ]
    con.execute("DROP TABLE IF EXISTS item_assets")
    con.execute(
        """
        CREATE TABLE item_assets (
            item_id UBIGINT,
            item_name VARCHAR,
            class_name VARCHAR,
            tier INTEGER,
            cost INTEGER,
            slot VARCHAR,
            active BOOLEAN,
            unique_item BOOLEAN,
            component_items_json VARCHAR
        )
        """
    )
    con.executemany("INSERT INTO item_assets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)


def _export(con: duckdb.DuckDBPyConnection, table: str, path: Path) -> None:
    con.execute(
        f"COPY {table} TO '{path}' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)"
    )


def _count(con: duckdb.DuckDBPyConnection, query: str) -> int:
    row = con.execute(query).fetchone()
    if row is None:
        raise RuntimeError(f"count query returned no row: {query}")
    return int(row[0])


def _execute_remote_query(
    con: duckdb.DuckDBPyConnection,
    query: str,
) -> duckdb.DuckDBPyConnection:
    """Retry when DuckLake publishes metadata just before a shard is readable."""
    for attempt in range(1, _REMOTE_QUERY_ATTEMPTS + 1):
        try:
            return con.execute(query)
        except duckdb.Error as error:
            retryable = any(marker in str(error) for marker in _RETRYABLE_REMOTE_ERRORS)
            if not retryable or attempt == _REMOTE_QUERY_ATTEMPTS:
                raise
            delay_s = 2 ** (attempt - 1)
            print(
                "Remote snapshot is still publishing; "
                f"retrying in {delay_s}s ({attempt}/{_REMOTE_QUERY_ATTEMPTS})…",
                flush=True,
            )
            time.sleep(delay_s)
    raise AssertionError("remote query retry loop exhausted")


def extract_cohort(paths: RunPaths, cohort: Cohort) -> dict[str, Any]:
    cohort.validate()
    con = _connect(paths)
    try:
        _load_item_assets(con, paths.raw / "items.json")
        con.execute("DROP TABLE IF EXISTS eligible_matches")
        _execute_remote_query(
            con, "CREATE TABLE eligible_matches AS " + _eligible_matches_query(cohort)
        )
        print("Extracting deidentified player-match cohort…", flush=True)
        con.execute("DROP TABLE IF EXISTS player_matches")
        _execute_remote_query(
            con,
            """
            CREATE TABLE player_matches AS
            SELECT
                match_id,
                player_slot,
                CASE WHEN team = 'Team0' THEN 0 ELSE 1 END AS team_id,
                hero_id,
                assigned_lane,
                average_badge,
                won,
                start_time,
                duration_s,
                net_worth AS final_net_worth,
                coalesce(player_rank_initial_calibration_games, 0) > 0 AS calibration
            FROM remote.main.match_player
            INNER JOIN eligible_matches USING (match_id)
            """,
        )
        print("Aggregating deidentified unique-player breadth…", flush=True)
        con.execute("DROP TABLE IF EXISTS hero_account_counts")
        _execute_remote_query(
            con,
            """
            CREATE TABLE hero_account_counts AS
            SELECT hero_id, count(DISTINCT account_id) AS unique_accounts
            FROM remote.main.match_player
            INNER JOIN eligible_matches USING (match_id)
            GROUP BY hero_id
            """,
        )
        con.execute(
            """
            CREATE OR REPLACE TABLE match_folds AS
            WITH matches AS (
                SELECT match_id, min(start_time) AS start_time
                FROM player_matches GROUP BY match_id
            ), boundaries AS (
                SELECT quantile_cont(epoch(start_time), 0.6) AS train_end,
                       quantile_cont(epoch(start_time), 0.8) AS validation_end
                FROM matches
            )
            SELECT match_id,
                   CASE
                       WHEN epoch(start_time) <= train_end THEN 'train'
                       WHEN epoch(start_time) <= validation_end THEN 'validation'
                       ELSE 'test'
                   END AS fold
            FROM matches, boundaries
            """
        )
        con.execute(
            """
            CREATE OR REPLACE TABLE compositions AS
            SELECT match_id, team_id, list_sort(list(hero_id)) AS hero_ids
            FROM player_matches GROUP BY match_id, team_id
            """
        )

        print("Extracting team net-worth snapshots…", flush=True)
        con.execute("DROP TABLE IF EXISTS team_snapshots")
        _execute_remote_query(
            con,
            """
            CREATE TABLE team_snapshots AS
            WITH snapshots AS (
                SELECT
                    match_id,
                    CASE WHEN team = 'Team0' THEN 0 ELSE 1 END AS team_id,
                    unnest("stats.time_stamp_s") AS stat_time,
                    unnest("stats.net_worth") AS player_net_worth
                FROM remote.main.match_player
                INNER JOIN eligible_matches USING (match_id)
            )
            SELECT match_id, team_id, stat_time,
                   sum(player_net_worth) AS team_net_worth,
                   count(*) AS observed_players
            FROM snapshots
            GROUP BY match_id, team_id, stat_time
            """,
        )

        print(
            "Extracting upgrade purchase events and valid pre-decision state…",
            flush=True,
        )
        con.execute("DROP TABLE IF EXISTS purchases")
        _execute_remote_query(
            con,
            """
            CREATE TABLE purchases AS
            WITH expanded AS (
                SELECT
                    match_id,
                    player_slot,
                    CASE WHEN team = 'Team0' THEN 0 ELSE 1 END AS team_id,
                    hero_id,
                    assigned_lane,
                    average_badge,
                    won,
                    start_time,
                    duration_s,
                    net_worth AS final_net_worth,
                    coalesce(player_rank_initial_calibration_games, 0) > 0 AS calibration,
                    unnest("items.item_id") AS item_id,
                    unnest("items.game_time_s") AS buy_time,
                    unnest("items.sold_time_s") AS sold_time,
                    unnest("items.imbued_ability_id") AS imbued_ability_id,
                    "stats.time_stamp_s" AS stat_times,
                    "stats.net_worth" AS stat_net_worths
                FROM remote.main.match_player
                INNER JOIN eligible_matches USING (match_id)
            ), valid AS (
                SELECT e.*,
                       a.item_name, a.class_name, a.tier, a.cost, a.slot,
                       a.active, a.unique_item, a.component_items_json,
                       list_last(list_transform(
                           list_filter(
                               list_zip(stat_times, stat_net_worths),
                               x -> x[1] <= buy_time
                           ),
                           x -> x[2]
                       )) AS own_net_worth_at_buy,
                       list_last(list_transform(
                           list_filter(
                               list_zip(stat_times, stat_net_worths),
                               x -> x[1] <= buy_time
                           ),
                           x -> x[1]
                       )) AS state_observed_at_s
                FROM expanded e
                INNER JOIN item_assets a USING (item_id)
                WHERE buy_time > 0
            )
            SELECT
                * EXCLUDE (stat_times, stat_net_worths),
                row_number() OVER (
                    PARTITION BY match_id, player_slot
                    ORDER BY buy_time, item_id
                ) AS event_order,
                count(*) OVER (
                    PARTITION BY match_id, player_slot, buy_time
                ) AS same_second_purchase_count,
                row_number() OVER (
                    PARTITION BY match_id, player_slot, item_id
                    ORDER BY buy_time, sold_time
                ) AS item_purchase_ordinal
            FROM valid
            """,
        )

        print("Joining purchase events to team state…", flush=True)
        con.execute("DROP TABLE IF EXISTS first_purchases")
        con.execute(
            """
            CREATE TABLE first_purchases AS
            WITH firsts AS (
                SELECT p.*, f.fold,
                       CASE
                           WHEN buy_time < 540 THEN 0
                           WHEN buy_time < 1200 THEN 1
                           WHEN buy_time < 1800 THEN 2
                           ELSE 3
                       END AS phase
                FROM purchases p
                JOIN match_folds f USING (match_id)
                WHERE item_purchase_ordinal = 1
            ), own_state AS (
                SELECT f.*, s.team_net_worth AS own_team_net_worth,
                       s.observed_players AS own_team_observed_players
                FROM firsts f
                ASOF LEFT JOIN team_snapshots s
                    ON f.match_id = s.match_id
                   AND f.team_id = s.team_id
                   AND f.buy_time >= s.stat_time
            ), both_states AS (
                SELECT o.*, s.team_net_worth AS enemy_team_net_worth,
                       s.observed_players AS enemy_team_observed_players
                FROM own_state o
                ASOF LEFT JOIN team_snapshots s
                    ON o.match_id = s.match_id
                   AND (1 - o.team_id) = s.team_id
                   AND o.buy_time >= s.stat_time
            )
            SELECT *,
                   own_team_net_worth - enemy_team_net_worth AS team_net_worth_lead,
                   buy_time - state_observed_at_s AS state_age_s,
                   sum(cost) OVER (
                       PARTITION BY match_id, player_slot
                       ORDER BY buy_time
                       RANGE BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                   ) AS prior_catalog_spend,
                   count(*) OVER (
                       PARTITION BY match_id, player_slot
                       ORDER BY buy_time
                       RANGE BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                   ) AS prior_purchase_count
            FROM both_states
            """
        )
        con.execute("DROP TABLE IF EXISTS decision_opportunities")
        con.execute(
            """
            CREATE TABLE decision_opportunities AS
            WITH realized AS (
                SELECT *
                FROM first_purchases
                WHERE same_second_purchase_count = 1
                QUALIFY row_number() OVER (
                    PARTITION BY match_id, player_slot, phase, tier
                    ORDER BY buy_time, item_id
                ) = 1
            ), slates AS (
                SELECT tier, list_sort(list(item_id)) AS item_ids
                FROM item_assets
                GROUP BY tier
            )
            SELECT r.*,
                   to_json(struct_pack(
                       item_ids := s.item_ids,
                       includes_save := true
                   )) AS candidate_slate_json,
                   cast(r.item_id AS VARCHAR) AS realized_action,
                   false AS save_action_observed
            FROM realized r
            JOIN slates s USING (tier)
            """
        )

        print("Exporting compressed analysis tables…", flush=True)
        for table in (
            "item_assets",
            "eligible_matches",
            "player_matches",
            "hero_account_counts",
            "match_folds",
            "compositions",
            "team_snapshots",
            "purchases",
            "first_purchases",
            "decision_opportunities",
        ):
            _export(con, table, paths.data / f"{table}.parquet")

        counts = {
            table: _count(con, f"SELECT count(*) FROM {table}")
            for table in (
                "player_matches",
                "match_folds",
                "purchases",
                "first_purchases",
                "decision_opportunities",
            )
        }
        counts["heroes"] = _count(
            con, "SELECT count(DISTINCT hero_id) FROM player_matches"
        )
        counts["hero_account_rows"] = _count(
            con, "SELECT count(*) FROM hero_account_counts"
        )
        counts["valid_purchase_net_worth"] = _count(
            con, "SELECT count(own_net_worth_at_buy) FROM first_purchases"
        )
        counts["valid_team_lead"] = _count(
            con, "SELECT count(team_net_worth_lead) FROM first_purchases"
        )
        return counts
    finally:
        con.close()
        temporary = paths.raw / "duckdb-tmp"
        if temporary.exists():
            shutil.rmtree(temporary)
