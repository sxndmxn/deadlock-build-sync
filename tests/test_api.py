from typing import Any

import pytest

from deadlock_build_sync.api import HERO_DURATION_BUCKETS, ApiError, DeadlockApi
from deadlock_build_sync.ranks import Rank, RankDivision, RankRange, RankTier
from deadlock_build_sync.snapshot import MatchMode


def test_all_analytics_queries_use_the_same_rank_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rank_range = RankRange(
        minimum=Rank(RankTier.ORACLE, RankDivision.THREE),
        maximum=Rank(RankTier.PHANTOM, RankDivision.FIVE),
    )
    api = DeadlockApi(
        rank_range=rank_range,
        match_mode=MatchMode.UNRANKED,
        as_of_timestamp=999,
    )
    calls: list[tuple[str, dict[str, Any]]] = []

    def record(path: str, params: dict[str, Any] | None = None) -> list[object]:
        calls.append((path, params or {}))
        return []

    monkeypatch.setattr(api, "get_json", record)

    api.item_stats(hero_id=1, min_unix_timestamp=123, min_matches=10)
    api.ability_order_stats(hero_id=1, min_unix_timestamp=123, min_matches=20)
    api.hero_stats_by_duration(min_unix_timestamp=123)
    api.hero_counter_stats(hero_id=1, min_unix_timestamp=123, same_lane=True)

    assert calls
    assert all(
        params["min_average_badge"] == rank_range.minimum.badge_id
        and params["max_average_badge"] == rank_range.maximum.badge_id
        for _, params in calls
    )
    assert all(params["match_mode"] == "unranked" for _, params in calls)
    assert all(params["game_mode"] == "normal" for _, params in calls)
    assert all(params["max_unix_timestamp"] == 999 for _, params in calls)

    ability = next(params for path, params in calls if "ability-order" in path)
    assert ability["min_ability_upgrades"] == 1
    assert ability["max_ability_upgrades"] == 16
    durations = [params for path, params in calls if path.endswith("hero-stats")]
    assert [params["max_duration_s"] for params in durations] == [
        maximum_exclusive - 1 for _, _, maximum_exclusive in HERO_DURATION_BUCKETS
    ]


def test_resolves_one_available_version_and_pins_every_asset_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = DeadlockApi(client_version=20)
    calls: list[tuple[str, dict[str, Any]]] = []

    def fixture(path: str, params: dict[str, Any] | None = None) -> list[Any]:
        calls.append((path, params or {}))
        if path.endswith("client-versions"):
            return [10, 20, 30]
        if path.endswith("ranks"):
            return [
                {"tier": tier, "name": RankTier(tier).label} for tier in range(1, 12)
            ]
        return []

    monkeypatch.setattr(api, "get_json", fixture)

    api.active_heroes()
    api.items()
    api.rank_catalog()

    asset_calls = [
        params for path, params in calls if path != "/v1/assets/client-versions"
    ]
    assert len([path for path, _ in calls if path.endswith("client-versions")]) == 1
    assert all(params["client_version"] == 20 for params in asset_calls)


def test_unavailable_explicit_version_fails_before_assets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = DeadlockApi(client_version=21)
    monkeypatch.setattr(api, "get_json", lambda _path, _params=None: [10, 20])

    with pytest.raises(ApiError, match="unavailable"):
        api.active_heroes()


def test_normal_ruleset_rejects_street_brawl_assets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = DeadlockApi(client_version=20)

    def fixture(path: str, _params: dict[str, Any] | None = None) -> list[Any]:
        if path.endswith("client-versions"):
            return [20]
        return [
            {"id": 1, "name": "Normal", "game_mode": "normal"},
            {"id": 2, "name": "Brawl", "game_mode": "street_brawl"},
        ]

    monkeypatch.setattr(api, "get_json", fixture)

    assert [hero["id"] for hero in api.active_heroes()] == [1]
    assert [item["id"] for item in api.items()] == [1]
