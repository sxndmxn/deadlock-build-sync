"""Compare legal choices at a frozen checkpoint without selecting future owners."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import duckdb

import math
from collections import Counter
from dataclasses import asdict, dataclass
from statistics import NormalDist

import polars as pl

from deadlock_build_sync.mechanics import ItemGraph, MechanicsError
from deadlock_build_sync.purchase_guidance_types import PurchaseState
from deadlock_build_sync.purchase_planner import (
    covered,
    first_checkpoint,
    plan_purchases,
)
from deadlock_build_sync.value_validation import (
    integer,
    number,
    object_dict,
    object_list,
)

from .core_policy_dr import cross_fitted_dr_contrast
from .discovery_types import Nomination
from .late_game import reconstruct_final_inventory


@dataclass(frozen=True)
class ChoiceObservation:
    row: dict[str, object]
    conditions: set[tuple[str, str | int]]


def decision_rows(
    con: duckdb.DuckDBPyConnection, hero: int, minimum: int = 11, maximum: int = 116
) -> list[dict[str, object]]:
    cursor = con.execute(
        """
        SELECT p.* EXCLUDE(own_team_net_worth, enemy_team_net_worth,
                          own_team_observed_players, enemy_team_observed_players,
                          team_net_worth_lead),
               d.partition, c.hero_ids AS enemy_heroes,
               own_state.team_net_worth AS own_team_net_worth,
               enemy_state.team_net_worth AS enemy_team_net_worth,
               own_state.observed_players AS own_team_observed_players,
               enemy_state.observed_players AS enemy_team_observed_players,
               own_state.team_net_worth-enemy_state.team_net_worth AS team_net_worth_lead,
               own_state.stat_time AS own_observed, enemy_state.stat_time AS enemy_observed
        FROM decision_opportunities p JOIN discovery_partitions d USING(match_id)
        JOIN compositions c ON p.match_id=c.match_id AND (1-p.team_id)=c.team_id
        ASOF LEFT JOIN team_snapshots own_state
          ON p.match_id=own_state.match_id AND p.team_id=own_state.team_id
             AND p.buy_time>own_state.stat_time
        ASOF LEFT JOIN team_snapshots enemy_state
          ON p.match_id=enemy_state.match_id AND (1-p.team_id)=enemy_state.team_id
             AND p.buy_time>enemy_state.stat_time
        WHERE p.hero_id=? AND p.average_badge BETWEEN ? AND ? AND d.partition IN ('discovery','validation')
          AND p.buy_time-p.state_observed_at_s BETWEEN 1 AND 300
        ORDER BY p.match_id,p.player_slot,p.buy_time
    """,
        [hero, minimum, maximum],
    )
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, values, strict=True)) for values in cursor.fetchall()]


def event_histories(
    con: duckdb.DuckDBPyConnection, hero: int, minimum: int = 11, maximum: int = 116
) -> dict[tuple[int, int], list[tuple[int, int, int, int]]]:
    rows = con.execute(
        """
        SELECT p.match_id,p.player_slot,p.team_id,p.item_id,p.buy_time,p.sold_time
        FROM purchases p JOIN discovery_partitions d USING(match_id)
        WHERE d.partition IN ('discovery','validation') AND p.match_id IN (
            SELECT match_id FROM player_matches WHERE hero_id=? AND average_badge BETWEEN ? AND ?
        ) ORDER BY p.match_id,p.player_slot,p.buy_time,p.event_order
    """,
        [hero, minimum, maximum],
    ).fetchall()
    result: dict[tuple[int, int], list[tuple[int, int, int, int]]] = {}
    for match, slot, team, item, bought, sold in rows:
        result.setdefault((int(match), int(slot)), []).append((
            int(team),
            int(item),
            int(bought),
            int(sold or 0),
        ))
    return result


def inventory_before(
    events: list[tuple[int, int, int, int]], clock: int, graph: ItemGraph
) -> tuple[int, ...]:
    return reconstruct_final_inventory(
        [
            (item, bought, sold if 0 < sold < clock else 0)
            for _, item, bought, sold in events
            if bought < clock
        ],
        graph.components,
    )


def checkpoint_rows(
    con: duckdb.DuckDBPyConnection,
    hero: int,
    graph: ItemGraph,
    minimum: int = 11,
    maximum: int = 116,
) -> list[dict[str, object]]:
    decisions = decision_rows(con, hero, minimum, maximum)
    histories = event_histories(con, hero, minimum, maximum)
    by_match: dict[int, list[list[tuple[int, int, int, int]]]] = {}
    for (match, _), events in histories.items():
        by_match.setdefault(match, []).append(events)
    for row in decisions:
        clock = integer(row["buy_time"])
        match, slot, team = (
            integer(row["match_id"]),
            integer(row["player_slot"]),
            integer(row["team_id"]),
        )
        row["owned_before"] = list(
            inventory_before(histories.get((match, slot), []), clock, graph)
        )
        enemies = set()
        enemy_observed = row.get("enemy_observed")
        fresh_enemy = (
            enemy_observed is not None and 0 < clock - integer(enemy_observed) <= 300
        )
        for events in by_match.get(match, []):
            if fresh_enemy and events and events[0][0] != team:
                enemies.update(
                    inventory_before(events, integer(enemy_observed) + 1, graph)
                )
        if not fresh_enemy:
            row["enemy_heroes"] = []
        row["enemy_items"] = sorted(enemies)
        row["fold"] = "train" if row["partition"] == "discovery" else "validation"
        complete = (
            row.get("own_team_observed_players") == 6
            and row.get("enemy_team_observed_players") == 6
            and row.get("own_observed") is not None
            and row.get("enemy_observed") is not None
            and 0 < clock - integer(row["own_observed"]) <= 300
            and 0 < clock - integer(row["enemy_observed"]) <= 300
        )
        total = number(row.get("own_team_net_worth") or 0) + number(
            row.get("enemy_team_net_worth") or 0
        )
        row["relative_wealth"] = (
            number(row["own_net_worth_at_buy"]) * 12 / total
            if complete and total > 0
            else None
        )
    return decisions


def conditions(row: dict[str, object]) -> set[tuple[str, str | int]]:
    result: set[tuple[str, str | int]] = set()
    relative = row.get("relative_wealth")
    if isinstance(relative, (int, float)):
        result.add((
            "relative_wealth",
            "behind" if relative < 0.90 else "ahead" if relative > 1.10 else "even",
        ))
    for field, condition in (
        ("enemy_heroes", "enemy_hero"),
        ("enemy_items", "enemy_item"),
    ):
        result.update(
            (condition, integer(item)) for item in object_list(row.get(field)) or []
        )
    return result


def legal_at(
    row: dict[str, object],
    nominee: Nomination,
    item: int,
    checkpoint: int,
    graph: ItemGraph,
) -> bool:
    path, core = tuple(nominee["guide"]["path"]), tuple(nominee["items"])
    owned = tuple(
        integer(value) for value in object_list(row.get("owned_before")) or []
    )
    current = first_checkpoint(graph, path, owned)
    if current != checkpoint or covered(graph, item, owned):
        return False
    try:
        plan_purchases(
            graph, path, core, {item: checkpoint}, state=PurchaseState(owned)
        )
        plan_purchases(graph, path, core, {}, state=PurchaseState(owned))
    except (MechanicsError, ValueError):
        return False
    return True


def freeze_candidates(
    rows: list[dict[str, object]], nominee: Nomination, graph: ItemGraph
) -> list[dict[str, object]]:
    if not nominee["guide"]["ready"]:
        return []
    timing = nominee["guide"]["purchase_timing"]
    result = []
    for value in object_list(timing.get("items")) or []:
        record = object_dict(value)
        if record is None:
            raise ValueError("Frozen optional timing is malformed")
        item = integer(record["item_id"])
        counts = [
            integer(count)
            for count in object_list(record.get("counts_by_checkpoint")) or []
        ]
        checkpoint = max(range(len(counts)), key=counts.__getitem__)
        if counts[checkpoint] < max(
            20, integer(record["buyers"]) * 0.1
        ) or checkpoint >= len(nominee["guide"]["path"]):
            continue
        result.extend(freeze_choice(rows, nominee, item, checkpoint, graph))
    return result


def freeze_choice(
    rows: list[dict[str, object]],
    nominee: Nomination,
    item: int,
    checkpoint: int,
    graph: ItemGraph,
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    try:
        plan_purchases(
            graph,
            tuple(nominee["guide"]["path"]),
            tuple(nominee["items"]),
            {item: checkpoint},
        )
    except (MechanicsError, ValueError):
        return result
    comparator = nominee["guide"]["path"][checkpoint]
    discovery = [
        row
        for row in rows
        if row["fold"] == "train"
        and row.get("relative_wealth") is not None
        and row["item_id"] in {item, comparator}
        and legal_at(row, nominee, item, checkpoint, graph)
    ]
    counts = Counter(
        (condition, trigger, integer(row["item_id"]))
        for row in discovery
        for condition, trigger in conditions(row)
    )
    triggers = {(condition, trigger) for condition, trigger, _action in counts}
    for condition, trigger in sorted(triggers, key=str):
        if (
            min(counts[condition, trigger, action] for action in (item, comparator))
            >= 20
        ):
            result.append({
                "item_id": item,
                "after_step": checkpoint,
                "comparator_item_id": comparator,
                "condition": condition,
                "value": trigger,
            })
    return result


def evaluate_candidates(
    rows: list[dict[str, object]],
    nominee: Nomination,
    candidates: list[dict[str, object]],
    graph: ItemGraph,
    hypotheses: int,
) -> dict[str, object]:
    admitted, audit = [], []
    critical = NormalDist().inv_cdf(1 - 0.025 / max(1, hypotheses))
    choice_rows: dict[tuple[int, int, int], list[ChoiceObservation]] = {}
    for candidate in candidates:
        item = integer(candidate["item_id"])
        comparator = integer(candidate["comparator_item_id"])
        frame = comparison_frame(rows, nominee, candidate, graph, choice_rows)
        if any(
            sum(
                row["fold"] == fold and row["item_id"] == action
                for row in frame.iter_rows(named=True)
            )
            < 20
            for fold in ("train", "validation")
            for action in (item, comparator)
        ):
            audit.append({
                **candidate,
                "admitted": False,
                "reason": "Insufficient support in a temporal fold",
            })
            continue
        try:
            contrast = cross_fitted_dr_contrast(frame, item, comparator)
        except (ValueError, RuntimeError) as error:
            audit.append({**candidate, "admitted": False, "reason": str(error)})
            continue
        record = object_dict(finite_values(asdict(contrast))) or {}
        lowers, widths = [], []
        for fold in ("train", "validation"):
            diagnostics = contrast.fold_diagnostics[fold]
            interval = object_list(diagnostics["interval"]) or []
            center = number(diagnostics["estimate"])
            radius = (number(interval[1]) - number(interval[0])) / 2 / 1.96 * critical
            lowers.append(center - radius)
            widths.append(2 * radius)
        lower = min(lowers)
        passes = contrast.admitted and lower > 0 and max(widths) <= 0.10
        evidence = {
            **record,
            "hypotheses": hypotheses,
            "lower_bound": lower,
            "test_evaluated": False,
            "gates": {
                "support": contrast.admitted,
                "overlap": contrast.admitted,
                "balance": contrast.admitted,
                "uncertainty": max(widths) <= 0.10,
                "temporal_stability": contrast.stable,
                "corrected_outcome": lower > 0,
                "legal_path": True,
                "pre_decision_cohort": True,
            },
        }
        branch = {
            **candidate,
            "support": contrast.support,
            "lower_bound": lower,
            "evidence": evidence,
        }
        audit.append({**branch, "admitted": passes})
        if passes:
            admitted.append(branch)
    return {"version": 1, "branches": admitted, "audit": audit, "test_evaluated": False}


def substitution_legal(
    row: dict[str, object], candidate: dict[str, object], graph: ItemGraph
) -> bool:
    substitution = object_dict(candidate.get("substitution"))
    if substitution is None:
        return True
    path = tuple(
        integer(value) for value in object_list(substitution.get("path")) or []
    )
    core = tuple(
        integer(value) for value in object_list(substitution.get("core")) or []
    )
    owned = tuple(
        integer(value) for value in object_list(row.get("owned_before")) or []
    )
    try:
        plan_purchases(graph, path, core, {}, state=PurchaseState(owned))
    except (MechanicsError, ValueError):
        return False
    return True


def finite_values(value: object) -> object:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    mapping = object_dict(value)
    if mapping is not None:
        return {key: finite_values(item) for key, item in mapping.items()}
    if isinstance(value, (list, tuple)):
        return [finite_values(item) for item in value]
    return value


def comparison_frame(
    rows: list[dict[str, object]],
    nominee: Nomination,
    candidate: dict[str, object],
    graph: ItemGraph,
    choice_rows: dict[tuple[int, int, int], list[ChoiceObservation]],
) -> pl.DataFrame:
    item, checkpoint, comparator = (
        integer(candidate["item_id"]),
        integer(candidate["after_step"]),
        integer(candidate["comparator_item_id"]),
    )
    key = item, checkpoint, comparator
    if key not in choice_rows:
        choice_rows[key] = [
            ChoiceObservation(row, conditions(row))
            for row in rows
            if row["item_id"] in {item, comparator}
            and row.get("relative_wealth") is not None
            and legal_at(row, nominee, item, checkpoint, graph)
        ]
    selected = [
        observation.row
        for observation in choice_rows[key]
        if (str(candidate["condition"]), candidate["value"]) in observation.conditions
        and substitution_legal(observation.row, candidate, graph)
    ]
    if not selected:
        return pl.DataFrame(
            schema={
                "match_id": pl.Int64,
                "player_slot": pl.Int64,
                "fold": pl.String,
                "item_id": pl.Int64,
            }
        )
    return pl.DataFrame(selected, infer_schema_length=None, strict=False).unique(
        subset=["match_id", "player_slot"], keep="first", maintain_order=True
    )
