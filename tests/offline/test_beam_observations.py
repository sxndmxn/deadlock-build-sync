"""Reject outcome leakage and stale or incomplete purchase states."""

import duckdb
import pytest

from deadlock_build_sync.offline.beam_model import load_beam_model
from tests.offline.sql_fixtures import load_fixture_sql
from tests.offline.test_beam_search import make_beam_values


def test_purchase_counts_use_discovery_and_strict_prior_complete_states() -> None:
    with duckdb.connect() as connection:
        connection.execute(load_fixture_sql("beam/create_purchase_observations.sql"))
        model = load_beam_model(connection, make_beam_values(), 71, 115)
        assert model.cells == {(0, 1, 1): (1, 1)}
        connection.execute(load_fixture_sql("beam/change_reserved_outcomes.sql"))
        repeated = load_beam_model(connection, make_beam_values(), 71, 115)
        assert repeated.cells == model.cells


def test_multiple_purchases_in_one_match_do_not_multiply_observations() -> None:
    with duckdb.connect() as connection:
        connection.execute(load_fixture_sql("beam/create_purchase_observations.sql"))
        connection.execute(load_fixture_sql("beam/insert_second_purchase.sql"))
        model = load_beam_model(connection, make_beam_values(), 71, 115)
    assert model.cells == {(0, 1, 1): (1, 1), (0, 1, 2): (1, 1)}


@pytest.mark.parametrize(
    ("duration", "purchases"), [(None, 0), (95, 0), (100, 1), (101, 1)]
)
def test_purchase_counts_require_a_recorded_match_duration(
    duration: int | None, purchases: int
) -> None:
    with duckdb.connect() as connection:
        connection.execute(load_fixture_sql("beam/create_purchase_observations.sql"))
        connection.execute(load_fixture_sql("beam/set_match_duration.sql"), [duration])
        model = load_beam_model(connection, make_beam_values(), 71, 115)
    assert sum(count for count, _wins in model.cells.values()) == purchases
