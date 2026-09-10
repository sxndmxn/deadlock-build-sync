"""Reject outcome leakage and stale or incomplete purchase states."""

import duckdb

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
