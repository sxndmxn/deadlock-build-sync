from typing import Any

import pytest

from deadlock_build_sync.api import DeadlockApi
from deadlock_build_sync.ranks import Rank, RankDivision, RankRange, RankTier


def test_all_analytics_queries_use_the_same_rank_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rank_range = RankRange(
        minimum=Rank(RankTier.ORACLE, RankDivision.THREE),
        maximum=Rank(RankTier.PHANTOM, RankDivision.FIVE),
    )
    api = DeadlockApi(rank_range=rank_range)
    calls: list[tuple[str, dict[str, Any]]] = []

    def record(path: str, params: dict[str, Any] | None = None) -> list[object]:
        calls.append((path, params or {}))
        return []

    monkeypatch.setattr(api, "get_json", record)

    api.item_stats(hero_id=1, min_unix_timestamp=123, min_matches=10)
    api.ability_order_stats(hero_id=1, min_unix_timestamp=123, min_matches=20)
    api.hero_stats_by_duration(min_unix_timestamp=123)

    assert calls
    assert all(
        params["min_average_badge"] == rank_range.minimum.badge_id
        and params["max_average_badge"] == rank_range.maximum.badge_id
        for _, params in calls
    )
