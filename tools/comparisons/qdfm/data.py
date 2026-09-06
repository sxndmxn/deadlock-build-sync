"""Build a reproducible complete-trajectory pilot from frozen public data."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import duckdb
import numpy as np

from tools.comparisons.qdfm.extract import HEROES, fingerprint
from tools.comparisons.qdfm.state import Catalog, Player, features, groups


def read_players(
    con: duckdb.DuckDBPyConnection, path: Path, catalog: Catalog
) -> dict[int, list[Player]]:
    players = defaultdict(list)
    cursor = con.execute("SELECT * FROM read_parquet(?)", [str(path)])
    for match, slot, hero, team, times, wealth, ids, buys, sales in cursor.fetchall():
        if len(times) != len(wealth) or list(times) != sorted(set(times)):
            continue
        players[int(match)].append(
            Player(
                int(slot),
                int(hero),
                int(team),
                times,
                wealth,
                catalog.purchases(ids, buys, sales),
            )
        )
    return players


def select_episodes(
    focal_rows: list[dict[str, object]],
    players: dict[int, list[Player]],
    catalog: Catalog,
) -> tuple[list, Counter, Counter, dict]:
    counts = Counter()
    action_counts = Counter()
    by_hero = defaultdict(Counter)
    episodes = []
    for row in focal_rows:
        if any(
            item not in catalog.index and item not in catalog.abilities
            for item in row["item_ids"]
        ):
            counts["unknown_or_retired_focal_items"] += 1
            continue
        match_players = players[int(row["match_id"])]
        focal = next(
            (player for player in match_players if player.slot == row["player_slot"]),
            None,
        )
        if focal is None:
            counts["missing_focal"] += 1
            continue
        actions = groups(focal.purchases)
        if not actions:
            counts["no_purchase_after_600s"] += 1
            continue
        if row["fold"] == "train":
            action_counts.update(bundle for _, bundle in actions)
            by_hero[focal.hero].update(bundle for _, bundle in actions)
        episodes.append((row, focal, actions))
    return episodes, counts, action_counts, by_hero


def reconstruct_states(
    catalog: Catalog,
    players: dict[int, list[Player]],
    row: dict[str, object],
    focal: Player,
    actions: list,
    vocabulary: list[tuple[int, ...]],
    hero_support: dict[int, np.ndarray],
    mask_cache: dict,
    action_index: dict,
) -> list:
    reconstructed = []
    for purchase_time, bundle in actions:
        result = features(
            catalog,
            players[int(row["match_id"])],
            focal,
            purchase_time,
            int(row["average_badge"]),
            int(row["assigned_lane"]),
        )
        if result is None:
            break
        state, owned = result
        cache_key = (focal.hero, owned)
        if cache_key not in mask_cache:
            mask_cache[cache_key] = hero_support[focal.hero] & np.array([
                catalog.legal_bundle(owned, candidate) for candidate in vocabulary
            ])
        mask = mask_cache[cache_key]
        action = action_index[bundle]
        if not mask[action]:
            break
        reconstructed.append((state, action, mask, purchase_time))
    return reconstructed


def transition_rows(
    reconstructed: list, episode_id: int, hero: int, *, won: bool
) -> list:
    rows = []
    for index, (state, action, mask, purchase_time) in enumerate(reconstructed):
        done = index == len(reconstructed) - 1
        next_state = np.zeros_like(state) if done else reconstructed[index + 1][0]
        next_mask = np.zeros_like(mask) if done else reconstructed[index + 1][2]
        if done:
            # Numeric placeholder only: terminal Bellman target never bootstraps.
            next_mask[0] = True
        rows.append((
            state,
            action,
            float(won) if done else 0,
            next_state,
            done,
            mask,
            next_mask,
            episode_id,
            hero,
            purchase_time,
            index,
        ))
    return rows


def reconstruct_episodes(
    episodes: list,
    catalog: Catalog,
    players: dict[int, list[Player]],
    vocabulary: list[tuple[int, ...]],
    hero_support: dict[int, np.ndarray],
    counts: Counter,
) -> tuple[dict, list]:
    action_index = {bundle: index for index, bundle in enumerate(vocabulary)}
    rows_by_fold = defaultdict(list)
    episode_metadata = []
    mask_cache = {}
    for ordinal, (row, focal, actions) in enumerate(episodes):
        if ordinal % 2000 == 0:
            print(f"Reconstructing episode {ordinal}/{len(episodes)}…", flush=True)
        if any(
            bundle not in action_index
            or not hero_support[focal.hero][action_index[bundle]]
            for _, bundle in actions
        ):
            counts[f"{row['fold']}:unsupported_action_episode"] += 1
            continue
        reconstructed = reconstruct_states(
            catalog,
            players,
            row,
            focal,
            actions,
            vocabulary,
            hero_support,
            mask_cache,
            action_index,
        )
        if len(reconstructed) != len(actions):
            counts[f"{row['fold']}:invalid_state_or_inventory_episode"] += 1
            continue
        episode_id = len(episode_metadata)
        episode_metadata.append({
            "match_id": int(row["match_id"]),
            "slot": focal.slot,
            "hero_id": focal.hero,
            "fold": row["fold"],
            "won": bool(row["won"]),
            "steps": len(actions),
        })
        rows_by_fold[row["fold"]].extend(
            transition_rows(reconstructed, episode_id, focal.hero, won=bool(row["won"]))
        )
    return rows_by_fold, episode_metadata


def prepare(source: Path, directory: Path, minimum: int) -> None:
    catalog = Catalog(source)
    con = duckdb.connect()
    print("Loading deidentified lobby context…", flush=True)
    players = read_players(con, directory / "lobby.parquet", catalog)
    columns = con.execute(
        "SELECT * FROM read_parquet(?) LIMIT 0", [str(directory / "focal.parquet")]
    ).description
    names = [column[0] for column in columns]
    focal_rows = [
        dict(zip(names, row, strict=True))
        for row in con.execute(
            "SELECT * FROM read_parquet(?) ORDER BY match_id,player_slot",
            [str(directory / "focal.parquet")],
        ).fetchall()
    ]
    episodes, counts, action_counts, by_hero = select_episodes(
        focal_rows, players, catalog
    )
    vocabulary = sorted(
        bundle for bundle, count in action_counts.items() if count >= minimum
    )
    hero_support = {
        hero: np.array([by_hero[hero][bundle] >= minimum for bundle in vocabulary])
        for hero in HEROES
    }
    print(
        f"Training vocabulary: {len(vocabulary)} actions, "
        f"{sum(len(bundle) > 1 for bundle in vocabulary)} simultaneous baskets",
        flush=True,
    )
    rows_by_fold, episode_metadata = reconstruct_episodes(
        episodes, catalog, players, vocabulary, hero_support, counts
    )
    output_counts = {}
    for fold, rows in rows_by_fold.items():
        arrays = list(zip(*rows, strict=True))
        fields = (
            "states",
            "actions",
            "rewards",
            "next_states",
            "done",
            "masks",
            "next_masks",
            "episode_ids",
            "hero_ids",
            "times",
            "step_indices",
        )
        payload = {
            name: np.asarray(values)
            for name, values in zip(fields, arrays, strict=True)
        }
        np.savez_compressed(directory / f"{fold}.npz", **payload)
        output_counts[fold] = {
            "transitions": len(rows),
            "episodes": len(set(payload["episode_ids"])),
        }
    names = [
        "time",
        "own_wealth",
        "lobby_median_wealth",
        "relative_wealth_gap",
        "lobby_wealth_percentile",
        "team_wealth_lead",
        "own_team_wealth_share",
        "richest_enemy_gap",
        "wealth_growth_300s",
        "wealth_growth_observed",
        "own_snapshot_age",
        "max_snapshot_age",
        "badge",
        "lane",
    ]
    names += [
        f"{kind}_hero:{hero}"
        for kind in ("own", "ally", "enemy")
        for hero in catalog.heroes
    ]
    names += [
        f"{kind}:{catalog.names[item]}"
        for kind in ("owned", "prior_purchases", "enemy_owned")
        for item in catalog.ids
    ]
    manifest = {
        "source": str(source),
        "input_sha256": {
            name: fingerprint(directory / name)
            for name in ("focal.parquet", "lobby.parquet")
        },
        "start_at_s": 600,
        "maximum_snapshot_age_s": 300,
        "minimum_train_hero_action_count": minimum,
        "actions": [
            {
                "item_ids": list(bundle),
                "name": " + ".join(catalog.names[item] for item in bundle),
                "train_count": action_counts[bundle],
            }
            for bundle in vocabulary
        ],
        "features": names,
        "exclusions": dict(counts),
        "folds": output_counts,
        "episodes": episode_metadata,
        "sha256": {
            f"{fold}.npz": fingerprint(directory / f"{fold}.npz")
            for fold in rows_by_fold
        },
        "limitations": [
            "Complete post-600s trajectories with supported baskets only; selection can bias outcomes.",
            "Recommendations are item targets; exact spendable cash and slot unlocks are unavailable.",
            "Relative wealth uses the latest strictly earlier observations, up to 300 seconds old.",
            "No future build labels, final wealth, final duration, or outcome appear in state features.",
            "Pilot conditions on hero and inventory; explicit build-identity constraints are not implemented.",
            "Enemy purchases are reconstructed from public match logs; live visibility may differ.",
        ],
    }
    (directory / "dataset.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(
        json.dumps({"folds": output_counts, "exclusions": dict(counts)}, indent=2),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--minimum", type=int, default=10)
    args = parser.parse_args()
    prepare(args.source, args.directory, args.minimum)
