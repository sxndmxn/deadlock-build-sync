"""Read-only, deidentified supplement for the QDFM research trial."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import duckdb

HEROES = {
    12: ("Kelvin", "easy"),
    1: ("Infernus", "easy"),
    63: ("Mina", "easy"),
    6: ("Abrams", "medium"),
    72: ("Billy", "medium"),
    17: ("Grey Talon", "medium"),
    20: ("Ivy", "hard"),
    35: ("Viscous", "hard"),
    8: ("McGinnis", "hard"),
}
REMOTE = "ducklake:https://s3-cache.deadlock-api.com/fast/db_snapshot.ducklake"


def sql_literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def fingerprint(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def extract(source: Path, output: Path, per_hero: int) -> None:
    output.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(output / "supplement.duckdb"))
    con.execute("SET threads=4; SET memory_limit='4GB'")
    con.execute(
        f"ATTACH {sql_literal(source / 'raw/analysis.duckdb')} AS frozen (READ_ONLY)"
    )
    con.execute("INSTALL ducklake; LOAD ducklake; INSTALL httpfs; LOAD httpfs")
    con.execute("""
        CREATE OR REPLACE SECRET deadlock_public (
            TYPE S3, KEY_ID '', SECRET '',
            ENDPOINT 's3-cache.deadlock-api.com', URL_STYLE 'path', USE_SSL true
        )
    """)
    con.execute(f"ATTACH {sql_literal(REMOTE)} AS remote (READ_ONLY)")
    hero_ids = ",".join(str(hero) for hero in HEROES)
    con.execute(f"""
        CREATE OR REPLACE TABLE selected AS
        SELECT p.*, f.fold FROM frozen.player_matches p
        JOIN frozen.match_folds f USING (match_id)
        WHERE hero_id IN ({hero_ids})
        QUALIFY row_number() OVER (
            PARTITION BY hero_id, fold ORDER BY hash(match_id, player_slot, 42)
        ) <= CASE WHEN fold='train' THEN {per_hero * 3 // 5}
                  ELSE {per_hero // 5} END
    """)
    con.execute("""
        CREATE OR REPLACE TABLE selected_matches AS
        SELECT DISTINCT match_id FROM selected
    """)
    print(
        "Extracting complete focal purchase arrays, including starting items…",
        flush=True,
    )
    con.execute("""
        CREATE OR REPLACE TABLE focal AS
        SELECT s.match_id, s.player_slot, s.hero_id, s.team_id,
               s.average_badge, s.assigned_lane, s.fold, s.start_time,
               s.duration_s, s.won,
               r.won AS remote_won,
               r."items.item_id" AS item_ids,
               r."items.game_time_s" AS buy_times,
               r."items.sold_time_s" AS sold_times
        FROM remote.main.match_player r
        JOIN selected s USING (match_id, player_slot)
    """)
    print(
        "Extracting all 12 players' timestamped wealth for the selected matches…",
        flush=True,
    )
    con.execute("""
        CREATE OR REPLACE TABLE lobby AS
        SELECT r.match_id, r.player_slot, r.hero_id,
               CASE WHEN r.team='Team0' THEN 0 ELSE 1 END AS team_id,
               r."stats.time_stamp_s" AS stat_times,
               r."stats.net_worth" AS net_worths,
               r."items.item_id" AS item_ids,
               r."items.game_time_s" AS buy_times,
               r."items.sold_time_s" AS sold_times
        FROM remote.main.match_player r
        JOIN selected_matches s USING (match_id)
    """)
    counts = dict(
        con.execute("""
        SELECT 'selected',count(*) FROM selected UNION ALL
        SELECT 'focal',count(*) FROM focal UNION ALL
        SELECT 'lobby',count(*) FROM lobby UNION ALL
        SELECT 'outcome_mismatches',count(*) FROM focal WHERE won != remote_won
    """).fetchall()
    )
    if counts["selected"] != counts["focal"] or counts["outcome_mismatches"]:
        raise ValueError(f"Supplement disagrees with frozen source: {counts}")
    for table in ("focal", "lobby"):
        path = sql_literal(output / f"{table}.parquet")
        con.execute(f"COPY {table} TO {path} (FORMAT PARQUET, COMPRESSION ZSTD)")
    counts["hero_folds"] = con.execute("""
        SELECT hero_id,fold,count(*) FROM focal GROUP BY ALL ORDER BY 1,2
    """).fetchall()
    con.close()
    manifest = {
        "source_run": str(source.resolve()),
        "source_manifest_sha256": fingerprint(source / "manifest.json"),
        "remote": REMOTE,
        "sampling": "hash(match_id, player_slot, 42), 60/20/20 chronological source folds",
        "requested_per_hero": per_hero,
        "hero_groups": HEROES,
        "counts": counts,
        "sha256": {
            name: fingerprint(output / name)
            for name in ("focal.parquet", "lobby.parquet")
        },
        "scope": "Public match telemetry only; no account IDs or Steam files.",
    }
    (output / "extraction.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(counts), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--per-hero", type=int, default=2000)
    args = parser.parse_args()
    extract(args.source, args.output, args.per_hero)
