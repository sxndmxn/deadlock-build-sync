import duckdb

from deadlock_build_sync.offline.config import sha256_json
from deadlock_build_sync.offline.production_items import (
    _build_item_evidence_payload,
    _query_path_cohort_summary,
)
from tests.offline.production_evidence_fixtures import (
    make_item_metric_row,
)
from tests.offline.sql_fixtures import load_fixture_sql


def test_item_payload_admits_only_supported_majority_imbue_target() -> None:
    assets: dict[int, dict[str, object]] = {40: {"id": 40, "name": "Frozen Shelter"}}
    fold_eligible = {"train": 100, "validation": 100, "test": 0}

    supported = _build_item_evidence_payload(
        make_item_metric_row(), assets, fold_eligible
    )
    weak = _build_item_evidence_payload(
        {**make_item_metric_row(), "target_matches": 49, "target_share": 0.49},
        assets,
        fold_eligible,
    )

    assert supported["imbue_target_ability_id"] == 40
    assert supported["imbue_target_ability"] == "Frozen Shelter"
    assert supported["imbue_target_matches"] == 75
    assert supported["imbue_target_share"] == 0.75
    assert sha256_json(supported) == (
        "51e300997477414bd41771eb506aaf5dfb8b652ae8137ab9d8a6c304eba76aa1"
    )
    assert weak["imbue_target_ability_id"] is None
    assert weak["imbue_observations"] == 0


def test_core_budget_summaries_ignore_test_rows() -> None:
    connection = duckdb.connect()
    try:
        connection.execute(load_fixture_sql("cohort/create_player_matches.sql"))
        connection.execute(load_fixture_sql("cohort/insert_player_matches.sql"))
        connection.execute(load_fixture_sql("cohort/create_match_folds.sql"))
        connection.execute(load_fixture_sql("cohort/insert_match_folds.sql"))
        cohort = _query_path_cohort_summary(
            connection,
            frozenset({(1, 0), (2, 0), (3, 0)}),
        )
    finally:
        connection.close()

    assert cohort == (3, 15_000)
