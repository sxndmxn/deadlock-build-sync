"""Keep checkpoint guide selection separate from validation outcomes."""

import duckdb
import pytest

from deadlock_build_sync.offline.beam_search import GroupSearchRequest, search_group
from deadlock_build_sync.offline.beam_support import BeamOwnership
from deadlock_build_sync.offline.discovery_data import build_hero_discovery_data
from tests.offline.discovery_fixtures import make_item_graph
from tests.offline.test_beam_search import make_beam_model, make_beam_values
from tools.beam_comparison import checkpoints


def test_validation_outcomes_cannot_change_checkpoint_nominations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph, values = make_item_graph(13), make_beam_values()
    result = search_group(
        GroupSearchRequest(
            graph,
            make_beam_model(graph),
            BeamOwnership(values, graph, 1),
            {},
            None,
            1,
            (0, 1, 2, 3),
        )
    )
    monkeypatch.setattr(
        checkpoints, "freeze_purchase_guide", lambda *_args, **_kwargs: {"ready": True}
    )
    with duckdb.connect() as connection:
        original = checkpoints.nominate_routes(connection, values, graph, result)
        assert original[0]
        values.won[values.fold_mask("validation")] ^= True
        repeated = checkpoints.nominate_routes(connection, values, graph, result)
    assert repeated == original


def test_empty_checkpoint_evaluation_reports_zero_coverage() -> None:
    data = build_hero_discovery_data(7, [], {}, make_item_graph())
    assert checkpoints.evaluate_selected(data, {"state": 1, "selected": []}) == {
        "estimates": [],
        "validation_matches": 0,
        "validation_state_matches": 0,
        "covered_validation_matches": 0,
        "covered_validation_state_matches": 0,
    }
