from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast, override

import pytest

from deadlock_build_sync.http_client import JsonHttpError, JsonHttpResponse
from deadlock_build_sync.offline import api as api_module
from deadlock_build_sync.offline.api import ApiClient, ApiError
from deadlock_build_sync.offline.config import Cohort, RunPaths

if TYPE_CHECKING:
    from pathlib import Path
    from typing import ClassVar

    from deadlock_build_sync.http_client import JsonHttpClient


class _FakeHttp:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.closed = False

    def get_json(
        self,
        path: str,
        _params: dict[str, object] | None = None,
    ) -> JsonHttpResponse:
        if self.fail:
            raise JsonHttpError("request failed")
        return JsonHttpResponse({"path": path}, b"{}", path)

    def close(self) -> None:
        self.closed = True


class _SourceClient:
    instances: ClassVar[list[_SourceClient]] = []

    def __init__(self) -> None:
        self.closed = False
        self.calls: list[tuple[str, dict[str, object] | None]] = []
        self.instances.append(self)

    def get(self, path: str, params: dict[str, object] | None = None) -> object:
        self.calls.append((path, params))
        responses: dict[str, object] = {
            "/v1/assets/client-versions": [121, 123, "bad"],
            "/v1/assets/heroes": [
                {
                    "id": 2,
                    "name": "Active",
                    "disabled": False,
                    "in_development": False,
                    "game_mode": "normal",
                },
                {"id": 1, "disabled": True},
                {"id": "bad"},
            ],
            "/v1/assets/items": [
                {
                    "id": 20,
                    "type": "upgrade",
                    "shopable": True,
                    "disabled": False,
                    "item_tier": 2,
                },
                {"id": 21, "type": "weapon", "shopable": True, "item_tier": 2},
                {"id": 22, "type": "upgrade", "shopable": False, "item_tier": 2},
            ],
            "/v1/assets/ranks": [{"name": "Oracle"}],
            "/v2/patches": [{"title": "Patch"}],
            "/openapi.json": {"openapi": "3.1.0"},
        }
        return responses[path]

    def close(self) -> None:
        self.closed = True


class _AuditClient:
    instances: ClassVar[list[_AuditClient]] = []

    def __init__(self) -> None:
        self.closed = False
        self.calls: list[str] = []
        self.instances.append(self)

    def get(self, path: str, params: dict[str, object] | None = None) -> object:
        self.calls.append(path)
        if (
            path == "/v1/analytics/item-flow-stats"
            and params is not None
            and params.get("hero_ids") == 1
        ):
            raise ApiError("flow unavailable")
        return [{"path": path}]

    def close(self) -> None:
        self.closed = True


def test_api_client_wraps_json_http_success_and_failure() -> None:
    client = ApiClient("https://example.test/")
    success = _FakeHttp()
    client._http.close()
    client._http = cast("JsonHttpClient", success)
    assert client.base_url == "https://example.test"
    assert client.get("/ok") == {"path": "/ok"}
    client.close()
    assert success.closed

    failure = _FakeHttp(fail=True)
    client._http = cast("JsonHttpClient", failure)
    with pytest.raises(ApiError, match="request failed"):
        client.get("/bad")


def test_source_capture_filters_and_writes_assets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _SourceClient.instances.clear()
    monkeypatch.setattr(api_module, "ApiClient", _SourceClient)
    paths = RunPaths.create(tmp_path, "sources")

    result = api_module.capture_sources(paths)

    assert result["client_version"] == 123
    assert result["active_heroes"] == 1
    assert result["shop_items"] == 1
    assert _SourceClient.instances[0].closed
    assert api_module.read_json(paths.raw / "heroes.json") == [
        {
            "disabled": False,
            "game_mode": "normal",
            "id": 2,
            "in_development": False,
            "name": "Active",
        }
    ]


def test_client_version_and_asset_validation_reject_bad_shapes() -> None:
    with pytest.raises(ApiError, match="was not a list"):
        api_module._latest_client_version({})
    with pytest.raises(ApiError, match="no numeric"):
        api_module._latest_client_version(["bad"])
    assert not api_module._active_hero({"id": 1, "in_development": True})
    assert not api_module._active_hero({"id": 1, "game_mode": "duel"})
    assert not api_module._shop_item({"id": 1, "item_tier": 5})
    assert not api_module._shop_item({"id": 1, "item_tier": "2"})


def test_api_audit_records_failures_and_duration_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _AuditClient.instances.clear()
    monkeypatch.setattr(api_module, "ApiClient", _AuditClient)
    paths = RunPaths.create(tmp_path, "audit")
    api_module.write_json(
        paths.raw / "heroes.json",
        [{"id": hero_id} for hero_id in range(1, 11)],
    )
    cohort = Cohort(
        since=datetime(2026, 8, 1, tzinfo=UTC),
        as_of=datetime(2026, 8, 2, tzinfo=UTC),
    )

    result = api_module.capture_api_audit(paths, cohort)

    assert result["calls"] == 26
    failures = result["failures"]
    assert isinstance(failures, list)
    assert len(failures) == 1
    assert _AuditClient.instances[0].closed
    assert "API audit: 10/10 heroes" in capsys.readouterr().out
    assert (paths.api / "hero-duration-50m-plus.json").exists()


def test_capture_rejects_invalid_source_assets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _BadSourceClient(_SourceClient):
        @override
        def get(self, path: str, params: dict[str, object] | None = None) -> object:
            if path == "/v1/assets/heroes":
                return {}
            return super().get(path, params)

    monkeypatch.setattr(api_module, "ApiClient", _BadSourceClient)
    with pytest.raises(ApiError, match="not an array"):
        api_module.capture_sources(RunPaths.create(tmp_path, "bad-sources"))


def test_api_audit_rejects_empty_hero_assets(tmp_path: Path) -> None:
    paths = RunPaths.create(tmp_path, "empty-audit")
    api_module.write_json(paths.raw / "heroes.json", [])

    with pytest.raises(ApiError, match="no objects"):
        api_module.capture_api_audit(paths, Cohort())
