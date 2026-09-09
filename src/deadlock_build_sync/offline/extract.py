from __future__ import annotations

import json
import shutil
import time
from dataclasses import replace
from pathlib import Path

import duckdb

from deadlock_build_sync.hero_cohort import calculate_rank_cutoffs

from .config import DUCKLAKE_URL, Cohort, RunPaths
from .sql_resources import load_sql

_REMOTE_QUERY_ATTEMPTS = 4
_RETRYABLE_REMOTE_ERRORS = (
    "No magic bytes found at end of file",
    "HTTP GET error",
    "Connection error",
)


def _build_cohort_parameters(cohort: Cohort) -> dict[str, object]:
    return {
        "match_mode": cohort.match_mode,
        "game_mode": cohort.game_mode,
        "since": cohort.since,
        "as_of": cohort.resolved_as_of(),
        "minimum_badge": cohort.minimum_badge,
        "maximum_badge": cohort.maximum_badge,
    }


def _connect_analysis_database(paths: RunPaths) -> duckdb.DuckDBPyConnection:
    database = paths.raw / "analysis.duckdb"
    connection = duckdb.connect(str(database))
    connection.execute(load_sql("extract/set_threads.sql"))
    connection.execute(load_sql("extract/set_memory_limit.sql"))
    connection.execute(
        load_sql("extract/set_temp_directory.sql"),
        {"directory": str(paths.raw / "duckdb-tmp")},
    )
    connection.execute(load_sql("extract/load_extensions.sql"))
    connection.execute(load_sql("extract/create_s3_secret.sql"))
    connection.execute(
        load_sql("extract/create_ducklake_secret.sql"),
        {"metadata_path": DUCKLAKE_URL.removeprefix("ducklake:")},
    )
    connection.execute(load_sql("extract/attach_remote.sql"))
    version = _query_count(connection, load_sql("extract/select_current_snapshot.sql"))
    connection.execute(load_sql("extract/detach_remote.sql"))
    connection.execute(
        load_sql("extract/attach_remote_snapshot.sql"), {"version": version}
    )
    connection.execute(
        load_sql("extract/create_source_snapshot.sql"), {"version": version}
    )
    return connection


def _load_item_assets(connection: duckdb.DuckDBPyConnection, path: Path) -> None:
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
    connection.execute(load_sql("extract/drop_item_assets.sql"))
    connection.execute(load_sql("extract/create_item_assets.sql"))
    connection.executemany(load_sql("extract/insert_item_assets.sql"), rows)


def _export_table(
    connection: duckdb.DuckDBPyConnection, table: str, path: Path
) -> None:
    connection.execute(
        load_sql("extract/export_table.sql"), {"table": table, "path": str(path)}
    )


def _query_count(
    connection: duckdb.DuckDBPyConnection,
    query: str,
    parameters: dict[str, object] | None = None,
) -> int:
    row = connection.execute(query, parameters).fetchone()
    if row is None:
        raise RuntimeError(f"count query returned no row: {query}")
    return int(row[0])


def _execute_remote_query(
    connection: duckdb.DuckDBPyConnection,
    query: str,
    parameters: dict[str, object] | None = None,
) -> duckdb.DuckDBPyConnection:
    """Retry when DuckLake metadata references a data file that is not yet readable."""
    attempt = 1
    while True:
        try:
            return connection.execute(query, parameters)
        except duckdb.Error as error:
            retryable = any(marker in str(error) for marker in _RETRYABLE_REMOTE_ERRORS)
            if not retryable or attempt >= _REMOTE_QUERY_ATTEMPTS:
                raise
            delay_s = 2 ** (attempt - 1)
            print(
                "Remote snapshot is still publishing; "
                f"retrying in {delay_s}s ({attempt}/{_REMOTE_QUERY_ATTEMPTS})…",
                flush=True,
            )
            time.sleep(delay_s)
            attempt += 1


def _freeze_splits(connection: duckdb.DuckDBPyConnection, cohort: Cohort) -> None:
    # Cutoffs use the starting cohort or fixed time fractions when that cohort is empty.
    connection.execute(
        load_sql("extract/create_split_boundaries.sql"),
        {"minimum_badge": cohort.minimum_badge, "maximum_badge": cohort.maximum_badge},
    )
    start, end = cohort.since.timestamp(), cohort.resolved_as_of().timestamp()
    connection.execute(
        load_sql("extract/fill_split_boundaries.sql"),
        {
            name: start + (end - start) * share
            for name, share in (
                ("discovery_end", 0.45),
                ("train_end", 0.6),
                ("validation_end", 0.8),
            )
        },
    )
    connection.execute(load_sql("extract/create_match_folds.sql"))


def extract_cohort(
    paths: RunPaths, cohort: Cohort, *, rank_expansion: str = "off"
) -> dict[str, object]:
    cohort.validate()
    cutoffs = calculate_rank_cutoffs(
        cohort.minimum_badge, cohort.maximum_badge, rank_expansion
    )
    extraction = replace(cohort, minimum_badge=cutoffs[-1])
    connection = _connect_analysis_database(paths)
    try:
        _load_item_assets(connection, paths.raw / "items.json")
        connection.execute(load_sql("extract/drop_eligible_matches.sql"))
        _execute_remote_query(
            connection,
            load_sql("extract/create_eligible_matches.sql"),
            _build_cohort_parameters(extraction),
        )
        print("Extracting deidentified player-match cohort…", flush=True)
        connection.execute(load_sql("extract/drop_player_matches.sql"))
        _execute_remote_query(
            connection,
            load_sql("extract/create_player_matches.sql"),
        )
        print("Aggregating deidentified unique-player breadth…", flush=True)
        connection.execute(load_sql("extract/drop_hero_account_counts.sql"))
        _execute_remote_query(
            connection,
            load_sql("extract/create_hero_account_counts.sql"),
        )
        _freeze_splits(connection, cohort)
        connection.execute(load_sql("extract/create_compositions.sql"))

        print("Extracting personal net-worth snapshots…", flush=True)
        connection.execute(load_sql("extract/drop_player_snapshots.sql"))
        _execute_remote_query(
            connection,
            load_sql("extract/create_player_snapshots.sql"),
        )

        print("Extracting team net-worth snapshots…", flush=True)
        connection.execute(load_sql("extract/drop_team_snapshots.sql"))
        _execute_remote_query(
            connection,
            load_sql("extract/create_team_snapshots.sql"),
        )

        print(
            "Extracting upgrade purchase events and valid pre-decision state…",
            flush=True,
        )
        connection.execute(load_sql("extract/drop_purchases.sql"))
        _execute_remote_query(
            connection,
            load_sql("extract/create_purchases.sql"),
        )

        print("Joining purchase events to team state…", flush=True)
        connection.execute(load_sql("extract/drop_first_purchases.sql"))
        connection.execute(load_sql("extract/create_first_purchases.sql"))
        connection.execute(load_sql("extract/drop_decision_opportunities.sql"))
        connection.execute(load_sql("extract/create_decision_opportunities.sql"))

        print("Exporting compressed analysis tables…", flush=True)
        for table in (
            "item_assets",
            "eligible_matches",
            "player_matches",
            "hero_account_counts",
            "match_folds",
            "split_boundaries",
            "compositions",
            "team_snapshots",
            "player_snapshots",
            "purchases",
            "first_purchases",
            "decision_opportunities",
        ):
            _export_table(connection, table, paths.data / f"{table}.parquet")

        counts: dict[str, object] = {
            table: _query_count(
                connection, load_sql("extract/count_table_rows.sql"), {"table": table}
            )
            for table in (
                "player_matches",
                "match_folds",
                "purchases",
                "first_purchases",
                "decision_opportunities",
            )
        }
        counts["source_snapshot_version"] = _query_count(
            connection, load_sql("extract/select_source_snapshot.sql")
        )
        counts["extracted_minimum_badge"] = extraction.minimum_badge
        counts["heroes"] = _query_count(
            connection, load_sql("extract/count_heroes.sql")
        )
        counts["hero_account_rows"] = _query_count(
            connection, load_sql("extract/count_hero_accounts.sql")
        )
        counts["valid_purchase_net_worth"] = _query_count(
            connection, load_sql("extract/count_purchase_net_worth.sql")
        )
        counts["valid_team_lead"] = _query_count(
            connection, load_sql("extract/count_team_lead.sql")
        )
        return counts
    finally:
        connection.close()
        temporary = paths.raw / "duckdb-tmp"
        if temporary.exists():
            shutil.rmtree(temporary)
