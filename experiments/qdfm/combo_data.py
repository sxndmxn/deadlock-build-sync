"""Freeze concurrent item ownership at fixed game times for association screening."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb

from experiments.qdfm.build_pool import load_pools
from experiments.qdfm.extract import HEROES, fingerprint
from experiments.qdfm.state import Catalog


def reconstruct_inventories(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("""
        CREATE TEMP TABLE inventories AS
        SELECT l.match_id, l.player_slot, l.landmark, list(DISTINCT p.item_id) AS owned_items
        FROM landmarks l JOIN hero_events p
          ON l.match_id=p.match_id AND l.player_slot=p.player_slot
         AND p.buy_time < l.landmark
         AND (p.sold_time=0 OR p.sold_time>=l.landmark)
        WHERE NOT EXISTS (
            SELECT 1 FROM hero_events u JOIN upgrades a ON a.parent=u.item_id
            WHERE u.match_id=p.match_id AND u.player_slot=p.player_slot
              AND a.child=p.item_id AND u.buy_time>=p.buy_time AND u.buy_time<l.landmark
        )
        GROUP BY l.match_id, l.player_slot, l.landmark
    """)


def extract(source: Path, evidence: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    pools, provenance = load_pools(evidence, source)
    catalog = Catalog(source)
    con = duckdb.connect(str(source / "raw/analysis.duckdb"), read_only=True)
    con.execute("SET threads=2")
    con.execute("SET memory_limit='2GB'")
    con.execute("CREATE TEMP TABLE pilot_heroes(hero_id INTEGER)")
    con.executemany("INSERT INTO pilot_heroes VALUES (?)", [(hero,) for hero in HEROES])
    con.execute("CREATE TEMP TABLE upgrades(parent BIGINT, child BIGINT)")
    con.executemany(
        "INSERT INTO upgrades VALUES (?, ?)",
        [
            (parent, child)
            for parent in catalog.ids
            for child in catalog.ancestors[parent]
        ],
    )
    con.execute("""
        CREATE TEMP TABLE landmarks AS
        SELECT p.match_id, p.player_slot, p.hero_id, p.team_id, p.average_badge,
               p.won, f.fold, t.landmark
        FROM player_matches p JOIN match_folds f USING(match_id)
        JOIN pilot_heroes h USING(hero_id)
        CROSS JOIN (VALUES (900), (1200), (1500)) t(landmark)
        WHERE f.fold IN ('train', 'validation') AND p.duration_s >= t.landmark
    """)
    con.execute("""
        CREATE TEMP TABLE hero_events AS
        SELECT p.* FROM purchases p JOIN pilot_heroes h USING(hero_id)
        JOIN match_folds f USING(match_id)
        WHERE f.fold IN ('train', 'validation') AND buy_time < 1500
    """)
    print("Reconstructing current inventory at 15, 20, and 25 minutes…", flush=True)
    reconstruct_inventories(con)
    con.execute("""
        CREATE TEMP TABLE observed AS
        SELECT l.*, p.own_net_worth_at_buy AS wealth,
               l.landmark-p.state_observed_at_s AS wealth_age_s,
               own.team_net_worth AS own_team_wealth,
               enemy.team_net_worth AS enemy_team_wealth,
               own.observed_players AS own_observed_players,
               enemy.observed_players AS enemy_observed_players,
               l.landmark-own.stat_time AS own_team_age_s,
               l.landmark-enemy.stat_time AS enemy_team_age_s
        FROM landmarks l ASOF LEFT JOIN hero_events p
          ON l.match_id=p.match_id AND l.player_slot=p.player_slot AND l.landmark>p.buy_time
        ASOF LEFT JOIN team_snapshots own
          ON l.match_id=own.match_id AND l.team_id=own.team_id AND l.landmark>own.stat_time
        ASOF LEFT JOIN team_snapshots enemy
          ON l.match_id=enemy.match_id AND (1-l.team_id)=enemy.team_id AND l.landmark>enemy.stat_time
    """)
    counts = con.execute("""
        SELECT count(*) AS total, count(*) FILTER (
            WHERE wealth>0 AND wealth_age_s<=300 AND own_team_age_s<=300
              AND enemy_team_age_s<=300 AND own_observed_players=6 AND enemy_observed_players=6
        ) AS retained FROM observed
    """).fetchone()
    con.execute(
        """
        COPY (
            SELECT o.*, i.owned_items,
                   (own_team_wealth-enemy_team_wealth)::DOUBLE /
                   greatest(own_team_wealth+enemy_team_wealth, 1) AS team_lead_share
            FROM observed o JOIN inventories i USING(match_id, player_slot, landmark)
            WHERE wealth>0 AND wealth_age_s<=300 AND own_team_age_s<=300
              AND enemy_team_age_s<=300 AND own_observed_players=6 AND enemy_observed_players=6
            ORDER BY hero_id, landmark, match_id, player_slot
        ) TO ? (FORMAT PARQUET)
    """,
        [str(output / "landmarks.parquet")],
    )
    actual = con.execute(
        "SELECT count(*) FROM read_parquet(?)", [str(output / "landmarks.parquet")]
    ).fetchone()[0]
    provenance.update({
        "source": str(source),
        "landmarks_s": [900, 1200, 1500],
        "primary_screen_landmark_s": 1200,
        "requested_pair_item_ids": [3791587546, 2095565695],
        "landmark_rows": counts[0],
        "fresh_observation_rows": counts[1],
        "retained_rows": actual,
        "landmarks_sha256": fingerprint(output / "landmarks.parquet"),
        "script_sha256": fingerprint(Path(__file__)),
        "protocol": {
            "candidate_pairs": "tier 2+ items admitted together in at least one selected build; exclude upgrade/component pairs",
            "screen": "four concurrent ownership groups at 20 minutes; train discovery and later validation replication",
            "adjustment": "current wealth in 5000-soul bins, team lead-share bins [-.10,-.03,.03,.10], badge in 20-point bins",
            "minimum_cell_per_stratum": 5,
            "minimum_joint_group_in_overlap": 50,
            "discovery_correction": "Benjamini-Hochberg across all estimable hero/pair training interactions",
            "replication_correction": "Bonferroni across discovery candidates, counting unestimable validation contrasts as failed replication",
            "interpretation": "observational additive interaction, not a causal purchase effect; current wealth may be affected by earlier items",
            "test_fold": "not read",
        },
        "path_count": len(pools),
    })
    (output / "data-manifest.json").write_text(json.dumps(provenance, indent=2) + "\n")
    print(json.dumps({"landmark_rows": counts[0], "retained_rows": actual}), flush=True)
    con.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--build-evidence", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    extract(args.source, args.build_evidence, args.output)
