import hashlib

import httpx
import pytest

from deadlock_build_sync.api import DeadlockApi
from deadlock_build_sync.http_client import JsonHttpClient, JsonHttpError
from deadlock_build_sync.snapshot import EvidenceRecorder


def test_json_http_client_retries_transient_status_with_retry_after() -> None:
    attempts = 0
    delays: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"retry-after": "3.5"})
        return httpx.Response(200, json={"ready": True})

    with JsonHttpClient(
        "https://example.test/api",
        timeout=1.0,
        max_attempts=3,
        transport=httpx.MockTransport(handler),
        sleeper=delays.append,
    ) as client:
        response = client.get_json("/status")

    assert response.data == {"ready": True}
    assert response.content == b'{"ready":true}'
    assert response.url == "https://example.test/api/status"
    assert attempts == 2
    assert delays == [3.5]


def test_json_http_client_fails_fast_on_non_retryable_client_error() -> None:
    attempts = 0
    delays: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(404, json={"detail": "missing"})

    with (
        JsonHttpClient(
            "https://example.test",
            timeout=1.0,
            max_attempts=5,
            transport=httpx.MockTransport(handler),
            sleeper=delays.append,
        ) as client,
        pytest.raises(JsonHttpError, match="404 Not Found"),
    ):
        client.get_json("/missing")

    assert attempts == 1
    assert delays == []


def test_deadlock_api_records_exact_httpx_response_and_normalized_query() -> None:
    raw = b'[{"id":1}]'

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["accept"] == "application/json"
        assert request.headers["user-agent"] == "deadlock-build-sync/0.1"
        assert dict(request.url.params) == {"only_active": "true"}
        return httpx.Response(200, content=raw)

    recorder = EvidenceRecorder()
    with DeadlockApi(
        "https://example.test",
        recorder=recorder,
        transport=httpx.MockTransport(handler),
    ) as api:
        assert api.get_json(
            "/v1/assets/heroes",
            {"only_active": True, "unused": None},
        ) == [{"id": 1}]

    record = recorder.records[0]
    assert record.parameters == {"only_active": "true"}
    assert record.byte_count == len(raw)
    assert record.sha256 == hashlib.sha256(raw).hexdigest()
