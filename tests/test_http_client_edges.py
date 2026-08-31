import httpx
import pytest

from deadlock_build_sync.http_client import JsonHttpClient, JsonHttpError


@pytest.mark.parametrize("base_url", ["relative/path", "ftp://example.test", "http://"])
def test_http_client_requires_an_absolute_http_url(base_url: str) -> None:
    with pytest.raises(ValueError, match="absolute HTTP"):
        JsonHttpClient(base_url, timeout=1.0, max_attempts=1)


def test_http_client_requires_a_positive_attempt_count() -> None:
    with pytest.raises(ValueError, match="max attempts must be positive"):
        JsonHttpClient("https://example.test", timeout=1.0, max_attempts=0)


def test_retry_delay_handles_missing_invalid_and_bounded_headers() -> None:
    request = httpx.Request("GET", "https://example.test")

    assert JsonHttpClient._retry_delay(2, None) == 4.0
    assert JsonHttpClient._retry_delay(0, httpx.Response(429, request=request)) == 1.0
    assert (
        JsonHttpClient._retry_delay(
            0,
            httpx.Response(429, headers={"retry-after": "bad"}, request=request),
        )
        == 1.0
    )
    assert (
        JsonHttpClient._retry_delay(
            0,
            httpx.Response(429, headers={"retry-after": "-2"}, request=request),
        )
        == 0.0
    )
    assert (
        JsonHttpClient._retry_delay(
            0,
            httpx.Response(429, headers={"retry-after": "60"}, request=request),
        )
        == 30.0
    )


def test_query_params_normalize_scalars_and_lists() -> None:
    assert JsonHttpClient._query_params({
        "flag": True,
        "none": None,
        "text": "value",
        "count": 2,
        "ratio": 0.5,
        "values": [True, False, None, "x", 3, 0.5],
    }) == {
        "flag": "true",
        "none": None,
        "text": "value",
        "count": 2,
        "ratio": 0.5,
        "values": ["true", "false", None, "x", 3, 0.5],
    }
    assert JsonHttpClient._query_params(None) is None


def test_query_params_reject_nested_and_unsupported_values() -> None:
    with pytest.raises(JsonHttpError, match="invalid query value for values"):
        JsonHttpClient._query_params({"values": [object()]})
    with pytest.raises(JsonHttpError, match="invalid query value for value"):
        JsonHttpClient._query_params({"value": object()})


def test_http_client_retries_server_error_with_exponential_delay() -> None:
    attempts = 0
    delays: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, json={"error": "busy"})
        return httpx.Response(200, json={"ok": True})

    with JsonHttpClient(
        "https://example.test",
        timeout=1.0,
        max_attempts=2,
        transport=httpx.MockTransport(handler),
        sleeper=delays.append,
    ) as client:
        assert client.get_json("/").data == {"ok": True}

    assert attempts == 2
    assert delays == [1.0]


def test_http_client_wraps_transport_and_json_errors() -> None:
    def offline(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    with (
        JsonHttpClient(
            "https://example.test",
            timeout=1.0,
            max_attempts=1,
            transport=httpx.MockTransport(offline),
        ) as client,
        pytest.raises(JsonHttpError, match="offline"),
    ):
        client.get_json("/")

    def malformed(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"{")

    with (
        JsonHttpClient(
            "https://example.test",
            timeout=1.0,
            max_attempts=1,
            transport=httpx.MockTransport(malformed),
        ) as client,
        pytest.raises(JsonHttpError, match="failed"),
    ):
        client.get_json("/")
