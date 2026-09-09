from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import httpx
import pytest

from deadlock_build_sync import http_client
from deadlock_build_sync.http_client import JsonHttpClient

if TYPE_CHECKING:
    from collections.abc import Callable


def _make_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[float], Callable[[float], None]]:
    clock = [100.0]
    monkeypatch.setattr(http_client.time, "monotonic", lambda: clock[0])

    def advance(delay: float) -> None:
        clock[0] += delay

    return clock, advance


def test_request_interval_applies_across_concurrent_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock, advance = _make_clock(monkeypatch)
    dispatched = []

    def handler(_request: httpx.Request) -> httpx.Response:
        dispatched.append(clock[0])
        return httpx.Response(200, json=[])

    with JsonHttpClient(
        "https://example.test",
        timeout=1,
        max_attempts=1,
        transport=httpx.MockTransport(handler),
        sleeper=advance,
    ) as client:
        client.set_request_interval(0.5)
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(client.get_json, ["/analytics"] * 8))
        with pytest.raises(ValueError, match="must not be negative"):
            client.set_request_interval(-1)
    assert dispatched == [100 + index * 0.5 for index in range(8)]


def test_retry_after_defers_the_shared_request_schedule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock, advance = _make_clock(monkeypatch)
    dispatched = []

    def handler(_request: httpx.Request) -> httpx.Response:
        dispatched.append(clock[0])
        return (
            httpx.Response(429, headers={"retry-after": "3"})
            if len(dispatched) == 1
            else httpx.Response(200, json=[])
        )

    with JsonHttpClient(
        "https://example.test",
        timeout=1,
        max_attempts=2,
        transport=httpx.MockTransport(handler),
        sleeper=advance,
    ) as client:
        client.set_request_interval(0.5)
        client.get_json("/analytics")
        client.get_json("/analytics")
    assert dispatched == [100, 103, 103.5]
