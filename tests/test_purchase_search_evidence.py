"""Check experiment cohort boundaries and complete-combination support."""

from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
import pytest

from tests.offline.sql_fixtures import load_fixture_sql
from tools.purchase_search.dataset import read_sql
from tools.purchase_search.evidence import JointSupport, OwnershipEvidence
from tools.purchase_search.records import CombinationConfig, Query
from tools.purchase_search.structures import community_proposals, mine_itemsets

from .test_purchase_search import catalog_fixture


def test_landmarks_follow_available_snapshot_boundaries() -> None:
    fixture = Path(__file__).parent / "offline/sql/search/create_landmark_fixture.sql"
    with duckdb.connect() as connection:
        connection.execute(fixture.read_text(encoding="utf-8"))
        connection.execute(
            read_sql("create_eligible_matches.sql"), {"partition": "train"}
        )
        rows = connection.execute(
            read_sql("select_landmarks.sql"),
            {"partition": "train", "hero": 1, "freshness": 120},
        ).fetchall()
    assert [(row[2], row[4], row[5]) for row in rows] == [
        (600, 1, 5000),
        (1201, 1, 12000),
        (1801, 1, 18000),
    ]


def test_missing_state_cohort_is_unavailable(tmp_path: Path) -> None:
    np.savez_compressed(
        tmp_path / "1-1201.npz",
        matrix=np.asarray([[True, False, True]]),
        matches=np.asarray([1]),
        won=np.asarray([True]),
        relative_state=np.asarray([-1]),
    )
    result = OwnershipEvidence(tmp_path).counts(1, 1201, 1, 1)
    assert result["available"] is False
    assert result["owners"] is None
    assert result["win_rate"] is None


def test_expanded_support_does_not_replace_exact_final_support(tmp_path: Path) -> None:
    catalog = catalog_fixture()
    np.savez_compressed(
        tmp_path / "1-1201.npz",
        matrix=np.asarray([[False, False, True]]),
        matches=np.asarray([1]),
        won=np.asarray([True]),
        relative_state=np.asarray([1]),
    )
    query = Query(1, "test", 800, 1, 800, 1600)
    support = JointSupport(
        OwnershipEvidence(tmp_path), catalog, query, 1201, CombinationConfig(1, 1)
    )
    component = 1 << 1
    upgrade = 1 << 2
    assert support.feasible(component)
    assert not support.complete(component)
    assert support.complete(upgrade)


def test_itemset_support_uses_intersections() -> None:
    patterns = dict(mine_itemsets((0b1111, 0b0111, 0b1001), 2, 3))
    assert patterns[0b011] == 3
    assert patterns[0b101] == 2
    assert 0b110 not in patterns
    assert 0b111 not in patterns


def test_leiden_seed_repeats_connected_communities() -> None:
    columns = (0b00001111, 0b00000111, 0b11110000, 0b11100000)
    first, details = community_proposals(columns, 8, 2, resolution=0.001, seed=7)
    second, _ = community_proposals(columns, 8, 2, resolution=0.001, seed=7)
    assert first == second == (0b0011, 0b1100)
    assert details["connected"] is True


def test_duplicate_hero_appearances_exclude_the_complete_match() -> None:
    with duckdb.connect() as connection:
        connection.execute(load_fixture_sql("search/create_duplicate_heroes.sql"))
        connection.execute(
            read_sql("create_eligible_matches.sql"), {"partition": "train"}
        )
        assert connection.execute(
            load_fixture_sql("search/select_experiment_matches.sql")
        ).fetchall() == [(1,)]


def test_duplicate_ownership_records_still_fail_validation(tmp_path: Path) -> None:
    np.savez_compressed(
        tmp_path / "1-1201.npz",
        matrix=np.asarray([[True], [True]]),
        matches=np.asarray([7, 7]),
        won=np.asarray([True, False]),
        relative_state=np.asarray([1, 1]),
    )
    with pytest.raises(ValueError, match="duplicate hero matches"):
        OwnershipEvidence(tmp_path).load(1, 1201)
