from __future__ import annotations

from datetime import UTC

import pytest

from deadlock_build_sync.api import ApiError, DeadlockApi
from deadlock_build_sync.api_models import (
    HeroDurationStat,
    Patch,
    calculate_patch_content_sha256,
    normalize_patch_content,
    normalize_patch_guid,
    parse_datetime,
    parse_duration_statistics,
)
from deadlock_build_sync.http_client import JsonHttpError, JsonHttpResponse
from deadlock_build_sync.ranks import RankCatalog
from deadlock_build_sync.snapshot import EpochBoundary, EpochSet


def _patch() -> Patch:
    return Patch("Patch", 100, "2026-01-01T00:00:00+00:00")


def _rank_catalog() -> RankCatalog:
    return RankCatalog({tier: f"Tier {tier}" for tier in range(1, 12)})


def test_constructor_rejects_nonpositive_client_version() -> None:
    with pytest.raises(ValueError, match="positive"):
        DeadlockApi(client_version=0)


def test_parameter_normalization_drops_none_and_formats_booleans() -> None:
    assert DeadlockApi._normalized_parameters({
        "true": True,
        "false": False,
        "none": None,
        "count": 2,
    }) == {"true": "true", "false": "false", "count": 2}
    assert DeadlockApi._normalized_parameters(None) == {}


def test_get_json_records_bytes_and_wraps_http_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = DeadlockApi()
    monkeypatch.setattr(
        api._http,
        "get_json",
        lambda _path, _params: JsonHttpResponse({"ok": True}, b"raw", "url"),
    )

    assert api.get_json("/v1/assets/heroes", {"active": True, "skip": None}) == {
        "ok": True
    }
    assert api.recorder.records[-1].byte_count == 3

    def fail(_path: str, _params: object) -> JsonHttpResponse:
        raise JsonHttpError("offline")

    monkeypatch.setattr(api._http, "get_json", fail)
    with pytest.raises(ApiError, match="offline"):
        api.get_json("/v1/assets/heroes")


def test_client_version_response_is_strict(monkeypatch: pytest.MonkeyPatch) -> None:
    api = DeadlockApi()
    monkeypatch.setattr(api, "get_json", lambda _path: {})
    with pytest.raises(ApiError, match="not a list"):
        api.resolve_client_version()

    monkeypatch.setattr(api, "get_json", lambda _path: ["1"])
    with pytest.raises(ApiError, match="no versions"):
        api.resolve_client_version()

    monkeypatch.setattr(api, "get_json", lambda _path: [1, 3, 2])
    assert api.resolve_client_version() == 3
    assert api.resolve_client_version() == 3


@pytest.mark.parametrize(
    ("method", "message"),
    [
        ("active_heroes", "active heroes"),
        ("items", "items response"),
        ("build_tags", "build-tag assets"),
        ("rank_catalog", "rank assets"),
    ],
)
def test_asset_methods_reject_nonlist_responses(
    method: str,
    message: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = DeadlockApi(client_version=1)
    api.client_version = 1
    monkeypatch.setattr(api, "get_json", lambda *_args, **_kwargs: {})
    with pytest.raises(ApiError, match=message):
        getattr(api, method)()


def test_active_heroes_filters_invalid_disabled_and_development_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = DeadlockApi(client_version=1)
    api.client_version = 1
    rows: list[object] = [
        {"id": 3},
        {"id": 1, "disabled": True},
        {"id": 2, "in_development": True},
        {"id": 4, "game_mode": "street_brawl"},
        {"id": "5"},
    ]
    monkeypatch.setattr(api, "get_json", lambda *_args, **_kwargs: rows)

    assert [hero["id"] for hero in api.active_heroes()] == [3]


def test_build_tags_and_rank_catalog_accept_valid_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = DeadlockApi(client_version=1)
    api.client_version = 1
    monkeypatch.setattr(api, "get_json", lambda *_args, **_kwargs: [{"id": 1}])
    assert api.build_tags() == [{"id": 1}]

    monkeypatch.setattr(
        api,
        "get_json",
        lambda *_args, **_kwargs: [
            {"tier": tier, "name": f"Tier {tier}"} for tier in range(1, 12)
        ],
    )
    assert api.rank_catalog().labels[1] == "Tier 1"


def test_current_patch_accepts_wrapped_feed_and_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = DeadlockApi()
    monkeypatch.setattr(
        api,
        "get_json",
        lambda _path: {
            "data": [
                {"title": "ignored"},
                {
                    "pub_date": "2026-01-01T00:00:00",
                    "content": "https://shared.akamai.steamstatic.com/a",
                },
            ]
        },
    )

    patch = api.current_patch()

    assert patch.title == "Current patch"
    assert patch.source == "unknown"
    assert patch.guid == "unknown"
    assert patch.start_timestamp == int(parse_datetime(patch.published_at).timestamp())


def test_current_patch_rejects_bad_shapes_and_empty_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = DeadlockApi()
    monkeypatch.setattr(api, "get_json", lambda _path: {})
    with pytest.raises(ApiError, match="patch list"):
        api.current_patch()

    monkeypatch.setattr(api, "get_json", lambda _path: [{"title": "No date"}])
    with pytest.raises(ApiError, match="current patch"):
        api.current_patch()


@pytest.mark.parametrize("response", [None, [], [1], [{}], [{"personaname": " "}]])
def test_steam_persona_rejects_missing_profile_data(
    response: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = DeadlockApi()
    monkeypatch.setattr(api, "get_json", lambda *_args: response)
    with pytest.raises(ApiError):
        api.steam_persona(12)


def test_steam_persona_strips_name(monkeypatch: pytest.MonkeyPatch) -> None:
    api = DeadlockApi()
    monkeypatch.setattr(
        api,
        "get_json",
        lambda *_args: [{"personaname": " Player "}],
    )
    assert api.steam_persona(12) == "Player"


def test_analytics_reject_start_after_cutoff() -> None:
    api = DeadlockApi(as_of_timestamp=100)
    with pytest.raises(ApiError, match="after the frozen"):
        api._analytic_parameters(min_unix_timestamp=101)


def test_item_and_ability_stats_cover_bucket_and_item_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = DeadlockApi(as_of_timestamp=100)
    calls: list[dict[str, object]] = []

    def rows(_path: str, params: dict[str, object]) -> list[dict[str, object]]:
        calls.append(params)
        return [{"ok": True}]

    monkeypatch.setattr(api, "get_json", rows)
    assert api.item_stats(
        hero_id=1,
        min_unix_timestamp=1,
        min_matches=2,
        bucket="10m",
    ) == [{"ok": True}]
    assert api.ability_order_stats(
        hero_id=1,
        min_unix_timestamp=1,
        min_matches=2,
        include_item_ids=(3, 4),
    ) == [{"ok": True}]
    assert calls[0]["bucket"] == "10m"
    assert calls[1]["include_item_ids"] == [3, 4]


@pytest.mark.parametrize("method", ["item_stats", "ability_order_stats"])
def test_analytic_rows_are_required(
    method: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = DeadlockApi(as_of_timestamp=100)
    monkeypatch.setattr(api, "get_json", lambda *_args, **_kwargs: {})
    kwargs = {"hero_id": 1, "min_unix_timestamp": 1, "min_matches": 2}
    with pytest.raises(ApiError, match="not a list"):
        getattr(api, method)(**kwargs)


def test_duration_and_counter_stats_reject_bad_shapes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = DeadlockApi(as_of_timestamp=100)
    monkeypatch.setattr(api, "get_json", lambda *_args, **_kwargs: {})
    with pytest.raises(ApiError, match="duration stats"):
        api.hero_stats_by_duration(min_unix_timestamp=1)
    with pytest.raises(ApiError, match="counter stats"):
        api.hero_counter_stats(min_unix_timestamp=1, same_lane=False)


def test_duration_stats_skip_invalid_rows_and_group_valid_points(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = DeadlockApi(as_of_timestamp=100)
    monkeypatch.setattr(
        api,
        "get_json",
        lambda *_args, **_kwargs: [
            None,
            {"hero_id": 12, "matches": 20, "wins": 11, "losses": 9},
        ],
    )

    curves = api.hero_stats_by_duration(min_unix_timestamp=1)

    assert len(curves[12]) == 7


def test_epoch_and_snapshot_defaults_are_explicit() -> None:
    patch = _patch()
    api = DeadlockApi(client_version=1, as_of_timestamp=200)
    api.client_version = 1
    api.recorder.record("/v1/assets/heroes", {}, b"record")
    epochs = api.epochs_for_patch(patch)
    assert epochs.mechanics.start_timestamp == 100
    assert api.analysis_start_timestamp(patch) == 100
    manifest = api.snapshot_manifest(
        patch=patch,
        rank_catalog=_rank_catalog(),
        build_tags_sha256="b" * 64,
    )
    assert len(manifest.warnings) == 2

    boundary = EpochBoundary("epoch", 50)
    configured = EpochSet(boundary, boundary, boundary, boundary)
    configured_api = DeadlockApi(client_version=1, epochs=configured)
    configured_api.client_version = 1
    configured_api.recorder.record("/v1/assets/heroes", {}, b"record")
    assert configured_api.epochs_for_patch(patch) is configured
    configured_manifest = configured_api.snapshot_manifest(
        patch=patch,
        rank_catalog=_rank_catalog(),
        build_tags_sha256="b" * 64,
    )
    assert configured_manifest.warnings == ()


def test_duration_stat_and_win_rate_validate_support() -> None:
    assert parse_duration_statistics(None, "phase", 0, 10) is None
    assert parse_duration_statistics({"hero_id": "12"}, "phase", 0, 10) is None
    assert (
        parse_duration_statistics(
            {"hero_id": 12, "matches": 19, "wins": 10, "losses": 9},
            "phase",
            0,
            10,
        )
        is None
    )
    assert (
        parse_duration_statistics(
            {"hero_id": 12, "matches": 20, "wins": 10, "losses": 9},
            "phase",
            0,
            10,
        )
        is None
    )
    resolved = parse_duration_statistics(
        {"hero_id": 12, "matches": 20, "wins": 11, "losses": 9},
        "phase",
        0,
        10,
    )
    assert resolved is not None
    assert resolved[1].win_rate == 0.55
    assert HeroDurationStat("none", 0, 1, 0, 0, 0).win_rate == 0.0


def test_patch_helpers_cover_dates_guids_and_nested_content() -> None:
    assert parse_datetime("2026-01-01T00:00:00").tzinfo == UTC
    with pytest.raises(ApiError, match="invalid current patch timestamp"):
        parse_datetime("bad")
    assert normalize_patch_guid(" value ") == "value"
    assert normalize_patch_guid({"key": "value"}) == '{"key":"value"}'
    assert normalize_patch_guid([1]) == "[1]"
    assert normalize_patch_guid(1) == "unknown"

    content = {
        "links": [
            "https://clan.fastly.steamstatic.com/a",
            "https://shared.akamai.steamstatic.com/b",
        ],
        "count": 1,
    }
    normalized = normalize_patch_content(content)
    assert normalized == {
        "links": [
            "https://clan.cdn.steamstatic.com/a",
            "https://shared.cdn.steamstatic.com/b",
        ],
        "count": 1,
    }
    assert calculate_patch_content_sha256(content) == calculate_patch_content_sha256(
        normalized
    )
