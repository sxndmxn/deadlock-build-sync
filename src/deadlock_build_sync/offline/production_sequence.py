from __future__ import annotations

from collections import Counter
from itertools import combinations
from typing import TYPE_CHECKING

import polars as pl

from deadlock_build_sync.build_evidence import (
    nondecreasing_window_schedule,
)
from deadlock_build_sync.mechanics import (
    InventoryState,
    ItemGraph,
    MechanicsError,
    purchase_item,
    schedule_component_path,
)
from deadlock_build_sync.value_validation import (
    integer,
    number,
    object_list,
)

from .config import RunPaths
from .production_policy import _purchase_priorities
from .production_sources import (
    SEQUENCE_MINIMUM_SUPPORT,
)

if TYPE_CHECKING:
    import duckdb


def _complete_priorities(
    priorities: dict[int, tuple[float, float, int]],
    graph: ItemGraph,
) -> dict[int, tuple[float, float, int]]:
    return {
        item_id: priorities.get(item_id, (float("inf"), float("inf"), item_id))
        for item_id in graph.nodes
    }


def _candidate_path_is_legal(
    candidate: dict[str, object],
    path: tuple[int, ...],
    graph: ItemGraph,
) -> bool:
    if len(path) != len(set(path)):
        return False
    state = InventoryState()
    try:
        for item_id in path:
            state = purchase_item(graph, state, item_id)
    except MechanicsError:
        return False
    return set(state.owned) == set(_candidate_item_ids(candidate))


def _candidate_item_ids(candidate: dict[str, object]) -> tuple[int, ...]:
    values = object_list(candidate.get("item_ids"))
    if values is None:
        raise RuntimeError("core candidate has no item list")
    return tuple(integer(item_id) for item_id in values)


def _ranked_agreement_orders(
    item_ids: tuple[int, ...],
    precedence: Counter[tuple[int, int]],
) -> list[tuple[int, tuple[int, ...]]]:
    ordered_items = tuple(sorted(item_ids))
    states: dict[int, dict[tuple[int, ...], int]] = {0: {(): 0}}
    full_mask = (1 << len(ordered_items)) - 1
    for mask in range(full_mask + 1):
        current = states.get(mask)
        if current is None:
            continue
        for index, item_id in enumerate(ordered_items):
            bit = 1 << index
            if mask & bit:
                continue
            added = sum(
                precedence[prior_id, item_id]
                for prior_index, prior_id in enumerate(ordered_items)
                if mask & (1 << prior_index)
            )
            target_mask = mask | bit
            target = states.setdefault(target_mask, {})
            for path, score in current.items():
                next_path = (*path, item_id)
                target[next_path] = score + added
    return sorted(
        ((score, path) for path, score in states[full_mask].items()),
        key=lambda value: (-value[0], value[1]),
    )


def _maximum_agreement_orders(
    item_ids: tuple[int, ...],
    precedence: Counter[tuple[int, int]],
) -> tuple[tuple[int, ...], tuple[int, ...], int, int]:
    """Return the best and runner-up target orders under pairwise agreement."""
    ranked = _ranked_agreement_orders(item_ids, precedence)
    best_score, best = ranked[0]
    runner_score, runner = ranked[1] if len(ranked) > 1 else ranked[0]
    return best, runner, best_score, runner_score


def _observed_purchase_precedence(
    rows: list[tuple[object, ...]],
    supporting_players: set[tuple[int, int]],
    item_ids: tuple[int, ...],
) -> Counter[tuple[int, int]]:
    observations: dict[tuple[int, int], dict[int, float]] = {}
    for match_id, player_slot, item_id, buy_time in rows:
        identity = integer(match_id), integer(player_slot)
        if identity in supporting_players:
            observations.setdefault(identity, {})[integer(item_id)] = number(buy_time)
    precedence: Counter[tuple[int, int]] = Counter()
    for times in observations.values():
        for first, second in combinations(item_ids, 2):
            if (
                first not in times
                or second not in times
                or times[first] == times[second]
            ):
                continue
            before, after = (
                (first, second) if times[first] < times[second] else (second, first)
            )
            precedence[before, after] += 1
    return precedence


def _feasible_core_orders(
    candidate: dict[str, object],
    item_ids: tuple[int, ...],
    precedence: Counter[tuple[int, int]],
    graph: ItemGraph,
    priorities: dict[int, tuple[float, float, int]],
    window_bounds: dict[int, tuple[float, float]],
) -> list[tuple[int, tuple[int, ...], tuple[int, ...], tuple[float, ...]]]:
    legal_orders = []
    for score, order in _ranked_agreement_orders(item_ids, precedence):
        try:
            path = schedule_component_path(graph, order, priorities)
        except MechanicsError:
            continue
        window_schedule = nondecreasing_window_schedule(path, window_bounds)
        if not _candidate_path_is_legal(candidate, path, graph):
            continue
        if window_schedule is None:
            continue
        legal_orders.append((score, order, path, window_schedule))
        if len(legal_orders) == 2:
            break
    return legal_orders


def _core_target_order(
    con: duckdb.DuckDBPyConnection,
    hero_id: int,
    candidate: dict[str, object],
    supporting_players: set[tuple[int, int]],
    graph: ItemGraph,
    priorities: dict[int, tuple[float, float, int]],
    window_bounds: dict[int, tuple[float, float]],
) -> tuple[tuple[int, ...], dict[str, object]]:
    item_ids = _candidate_item_ids(candidate)
    placeholders = ", ".join("?" for _ in item_ids)
    rows = con.execute(
        f"""
        SELECT match_id, player_slot, item_id, min(buy_time) AS buy_time
        FROM first_purchases
        WHERE hero_id = ? AND item_id IN ({placeholders})
        GROUP BY match_id, player_slot, item_id
        ORDER BY match_id, player_slot, buy_time
        """,
        [hero_id, *item_ids],
    ).fetchall()
    precedence = _observed_purchase_precedence(rows, supporting_players, item_ids)
    legal_orders = _feasible_core_orders(
        candidate, item_ids, precedence, graph, priorities, window_bounds
    )
    if not legal_orders:
        raise RuntimeError(
            f"hero {hero_id} core has no mechanics- and soul-window-feasible "
            "target order"
        )
    best_score, best, best_path, best_window_schedule = legal_orders[0]
    runner_score, runner, _, _ = (
        legal_orders[1] if len(legal_orders) > 1 else legal_orders[0]
    )
    common_prefix = next(
        (
            index
            for index, (left, right) in enumerate(zip(best, runner, strict=True))
            if left != right
        ),
        len(best),
    )
    return best, {
        "method": "window_constrained_pairwise_target_precedence_subset_dp",
        "window_constraint": "nondecreasing_first_ownership_iqr",
        "window_schedule": [
            {
                "item_id": item_id,
                "window_available": item_id in window_bounds,
                "minimum_feasible_net_worth": (
                    checkpoint if item_id in window_bounds else None
                ),
            }
            for item_id, checkpoint in zip(best_path, best_window_schedule, strict=True)
        ],
        "target_order": list(best),
        "agreement_support": best_score,
        "runner_up_order": list(runner),
        "runner_up_support": runner_score,
        "near_variant": (
            best_score > 0 and runner_score >= 0.9 * best_score and common_prefix <= 5
        ),
    }


def _expanded_default_path(
    default_item_ids: tuple[int, ...],
    hero_metrics: pl.DataFrame,
    graph: ItemGraph,
) -> list[int]:
    if not default_item_ids:
        raise RuntimeError("hero has no supported state-aware core")
    priorities = _complete_priorities(_purchase_priorities(hero_metrics), graph)
    path = schedule_component_path(graph, default_item_ids, priorities)
    candidate: dict[str, object] = {"item_ids": list(default_item_ids)}
    if not _candidate_path_is_legal(candidate, path, graph):
        raise RuntimeError("component-expanded default path is not a legal final core")
    return list(path)


def _sequence_rows(
    con: duckdb.DuckDBPyConnection,
    hero_id: int,
    member_ids: frozenset[tuple[int, int]] | None = None,
) -> list[dict[str, object]]:
    join = ""
    if member_ids is not None:
        members = pl.DataFrame({
            "match_id": [identity[0] for identity in member_ids],
            "player_slot": [identity[1] for identity in member_ids],
        })
        con.register("_sequence_path_members", members)
        join = "JOIN _sequence_path_members m USING (match_id, player_slot)"
    try:
        rows = con.execute(
            f"""
        WITH timestamped AS (
            SELECT p.*, count(*) OVER (
                PARTITION BY p.match_id, p.player_slot, p.buy_time
            ) AS bucket_size
            FROM first_purchases p
            {join}
            WHERE p.fold = 'train' AND p.hero_id = ?
        ), numbered AS (
            SELECT match_id, player_slot, item_id,
                   row_number() OVER (
                       PARTITION BY match_id, player_slot ORDER BY buy_time
                   ) - 1 AS position,
                   lag(item_id, 1, 0) OVER (
                       PARTITION BY match_id, player_slot ORDER BY buy_time
                   ) AS previous_item_id,
                   first_value(item_id) OVER (
                       PARTITION BY match_id, player_slot ORDER BY buy_time
                   ) AS observed_first_item_id
            FROM timestamped
            WHERE bucket_size = 1
        )
        SELECT CASE WHEN position = 0 THEN 0 ELSE observed_first_item_id END,
               previous_item_id, position, item_id
        FROM numbered
        ORDER BY match_id, player_slot, position
        """,
            [hero_id],
        ).fetchall()
    finally:
        if member_ids is not None:
            con.unregister("_sequence_path_members")
    events = [tuple(int(value) for value in row) for row in rows]
    specifications = (
        ("first_previous_position", (0, 1, 2)),
        ("previous_position", (1, 2)),
        ("position", (2,)),
        ("popularity", ()),
    )
    output: list[dict[str, object]] = []
    for level, indices in specifications:
        counts: Counter[tuple[tuple[int, ...], int]] = Counter()
        contexts: Counter[tuple[int, ...]] = Counter()
        for first_item, previous_item, position, next_item in events:
            values = (first_item, previous_item, position)
            context = tuple(values[index] for index in indices)
            counts[context, next_item] += 1
            contexts[context] += 1
        for (context, next_item), support in sorted(
            counts.items(),
            key=lambda value: (value[0][0], -value[1], value[0][1]),
        ):
            if support < SEQUENCE_MINIMUM_SUPPORT:
                continue
            context_values = dict(zip(indices, context, strict=True))
            output.append({
                "level": level,
                "first_item_id": context_values.get(0, 0),
                "previous_item_id": context_values.get(1, 0),
                "position": context_values.get(2, 0),
                "next_item_id": next_item,
                "support": support,
                "context_support": contexts[context],
            })
    if not output:
        raise RuntimeError(f"hero {hero_id} has no supported sequence transitions")
    return output


def _sequence_evaluation(paths: RunPaths, hero_id: int) -> list[dict[str, object]]:
    path = paths.tables / "sequence_model_evaluation.csv"
    if not path.is_file():
        return []
    frame = pl.read_csv(path).filter(pl.col("hero_id") == hero_id)
    return frame.to_dicts()


def _replacement_is_legal(
    default_item_ids: tuple[int, ...],
    comparator_item_id: int,
    alternative_item_id: int,
    graph: ItemGraph,
    priorities: dict[int, tuple[float, float, int]],
) -> bool:
    replacement = tuple(
        alternative_item_id if item_id == comparator_item_id else item_id
        for item_id in default_item_ids
    )
    if len(set(replacement)) != len(default_item_ids):
        return False
    candidate: dict[str, object] = {"item_ids": list(replacement)}
    try:
        path = schedule_component_path(graph, replacement, priorities)
    except MechanicsError:
        return False
    return _candidate_path_is_legal(candidate, path, graph)
