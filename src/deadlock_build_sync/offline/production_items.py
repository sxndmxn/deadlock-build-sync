from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from deadlock_build_sync.build_evidence import (
    MINIMUM_IMBUE_SHARE,
    MINIMUM_IMBUE_SUPPORT,
)
from deadlock_build_sync.value_validation import (
    integer,
    number,
)

if TYPE_CHECKING:
    import duckdb


def _query_path_cohort_summary(
    connection: duckdb.DuckDBPyConnection,
    member_ids: frozenset[tuple[int, int]],
) -> tuple[int, int | None]:
    members = pl.DataFrame({
        "match_id": [identity[0] for identity in member_ids],
        "player_slot": [identity[1] for identity in member_ids],
    })
    connection.register("_build_path_members", members)
    try:
        row = connection.execute(
            """
            SELECT count(*),
                   median(final_net_worth) FILTER (
                       WHERE f.fold IN ('train', 'validation')
                   )
            FROM player_matches p
            JOIN _build_path_members m USING (match_id, player_slot)
            JOIN match_folds f USING (match_id)
            """
        ).fetchone()
    finally:
        connection.unregister("_build_path_members")
    if row is None:
        raise RuntimeError("build path has no cohort summary")
    return int(row[0]), int(row[1]) if row[1] is not None else None


def _optional_float(value: object) -> float | None:
    return number(value) if value is not None else None


def _build_item_evidence_payload(
    row: dict[str, object],
    assets_by_id: dict[int, dict[str, object]],
    fold_eligible_matches: dict[str, int],
) -> dict[str, object]:
    target_id = row.get("imbued_ability_id")
    target_id = integer(target_id) if target_id is not None else None
    target_matches = integer(row.get("target_matches"), default=0)
    observations = integer(row.get("imbue_observations"), default=0)
    target_share = number(row.get("target_share") or 0.0)
    target = assets_by_id.get(target_id, {}) if target_id else {}
    target_name = target.get("name")
    target_supported = (
        isinstance(target_name, str)
        and bool(target_name.strip())
        and target_matches >= MINIMUM_IMBUE_SUPPORT
        and target_share > MINIMUM_IMBUE_SHARE
    )
    training_eligible = fold_eligible_matches["train"]
    validation_eligible = fold_eligible_matches["validation"]
    test_eligible = fold_eligible_matches["test"]
    selection_eligible = training_eligible + validation_eligible
    training_adopters = integer(row["training_adopter_matches"])
    validation_adopters = integer(row["validation_adopter_matches"])
    test_adopters = integer(row["test_adopter_matches"])
    selection_adopters = integer(row["selection_adopter_matches"])
    return {
        "item_id": integer(row["item_id"]),
        "item": str(row["item_name"]),
        "tier": integer(row["tier"]),
        "cost": integer(row["cost"]),
        "slot": str(row["slot"]),
        "active": bool(row["active"]),
        "adopter_matches": integer(row["adopter_matches"]),
        "eligible_player_matches": integer(row["hero_player_matches"]),
        "purchase_events": integer(row["purchase_events"]),
        "wins": integer(row["wins"]),
        "adoption": number(row["adoption_rate"]),
        "observed_outcome_rate": number(row["raw_outcome_rate"]),
        "median_buy_time_s": number(row["median_buy_time_s"]),
        "median_valid_buy_net_worth": _optional_float(
            row["median_valid_buy_net_worth"]
        ),
        "buy_net_worth_q25": _optional_float(row["buy_nw_q25"]),
        "buy_net_worth_q75": _optional_float(row["buy_nw_q75"]),
        "valid_buy_net_worth_share": number(row["valid_buy_nw_share"]),
        "selection_adopter_matches": selection_adopters,
        "selection_eligible_player_matches": selection_eligible,
        "training_adopter_matches": training_adopters,
        "training_eligible_player_matches": training_eligible,
        "validation_adopter_matches": validation_adopters,
        "validation_eligible_player_matches": validation_eligible,
        "test_adopter_matches": test_adopters,
        "test_eligible_player_matches": test_eligible,
        "selection_adoption": selection_adopters / selection_eligible,
        "training_adoption": training_adopters / training_eligible,
        "validation_adoption": validation_adopters / validation_eligible
        if validation_eligible
        else 0.0,
        "test_adoption": test_adopters / test_eligible if test_eligible else 0.0,
        "selection_median_buy_time_s": _optional_float(
            row["selection_median_buy_time_s"]
        ),
        "selection_median_valid_buy_net_worth": _optional_float(
            row["selection_median_valid_buy_net_worth"]
        ),
        "selection_buy_net_worth_q25": _optional_float(row["selection_buy_nw_q25"]),
        "selection_buy_net_worth_q75": _optional_float(row["selection_buy_nw_q75"]),
        "selection_valid_buy_net_worth_share": (
            integer(row["selection_valid_buy_nw_observations"]) / selection_adopters
            if selection_adopters
            else 0.0
        ),
        "selection_valid_buy_net_worth_observations": (
            integer(row["selection_valid_buy_nw_observations"])
        ),
        "training_valid_buy_net_worth_observations": integer(
            row["training_valid_buy_nw_observations"]
        ),
        "validation_valid_buy_net_worth_observations": integer(
            row["validation_valid_buy_nw_observations"]
        ),
        "training_buy_net_worth_q25": _optional_float(row["training_buy_nw_q25"]),
        "training_buy_net_worth_q75": _optional_float(row["training_buy_nw_q75"]),
        "validation_buy_net_worth_q25": _optional_float(row["validation_buy_nw_q25"]),
        "validation_buy_net_worth_q75": _optional_float(row["validation_buy_nw_q75"]),
        "imbue_target_ability_id": target_id if target_supported else None,
        "imbue_target_ability": target_name.strip() if target_supported else None,
        "imbue_target_matches": target_matches if target_supported else 0,
        "imbue_observations": observations if target_supported else 0,
        "imbue_target_share": target_share if target_supported else 0.0,
    }
