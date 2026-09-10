from __future__ import annotations

import json
import time
from dataclasses import dataclass
from threading import Lock
from typing import TYPE_CHECKING, Self

import httpx

from .value_validation import object_list

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

type _QueryScalar = str | int | float | None
type _QueryValue = _QueryScalar | list[_QueryScalar]


class JsonHttpError(RuntimeError):
    """Raised when a JSON endpoint remains unavailable or invalid."""


@dataclass(frozen=True)
class JsonHttpResponse:
    """A decoded JSON response with the original evidence bytes."""

    data: object
    content: bytes
    url: str


class JsonHttpClient:
    """Small shared HTTPX client for retrying JSON GET requests."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float,
        max_attempts: int,
        transport: httpx.BaseTransport | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        parsed_url = httpx.URL(base_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.host:
            raise ValueError("base URL must be an absolute HTTP(S) URL")
        if max_attempts < 1:
            raise ValueError("max attempts must be positive")
        self.base_url = base_url.rstrip("/")
        self.max_attempts = max_attempts
        self._sleeper = sleeper
        self._minimum_interval = 0.0
        self._request_lock = Lock()
        self._next_request_at = 0.0
        self._client = httpx.Client(
            base_url=f"{self.base_url}/",
            timeout=timeout,
            headers={
                "Accept": "application/json",
                "User-Agent": "deadlock-build-sync/0.1",
            },
            follow_redirects=True,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def set_request_interval(self, minimum_interval: float) -> None:
        if minimum_interval < 0:
            raise ValueError("Request interval must not be negative")
        with self._request_lock:
            self._minimum_interval = minimum_interval

    def __enter__(self) -> Self:
        """Return this open connection pool.

        Returns:
            This JSON client.

        """
        return self

    def __exit__(self, *_: object) -> None:
        """Close the connection pool when leaving its context."""
        self.close()

    @staticmethod
    def _retry_delay(attempt: int, response: httpx.Response | None) -> float:
        if response is not None and response.status_code == 429:
            try:
                retry_after = float(response.headers["retry-after"])
            except (KeyError, ValueError):
                pass
            else:
                return min(30.0, max(0.0, retry_after))
        return float(2**attempt)

    def _wait_for_request_slot(self) -> None:
        if not self._minimum_interval:
            return
        with self._request_lock:
            delay = self._next_request_at - time.monotonic()
            if delay > 0:
                self._sleeper(delay)
            self._next_request_at = time.monotonic() + self._minimum_interval

    def _postpone_requests(self, delay: float) -> None:
        with self._request_lock:
            self._next_request_at = max(self._next_request_at, time.monotonic() + delay)

    @staticmethod
    def _query_params(
        params: Mapping[str, object] | None,
    ) -> dict[str, _QueryValue] | None:
        normalized: dict[str, _QueryValue] = {}
        for key, value in (params or {}).items():
            if isinstance(value, bool):
                normalized[key] = str(value).lower()
            elif value is None or isinstance(value, str | int | float):
                normalized[key] = value
            elif (values := object_list(value)) is not None:
                items: list[_QueryScalar] = []
                for item in values:
                    if isinstance(item, bool):
                        items.append(str(item).lower())
                    elif item is None or isinstance(item, str | int | float):
                        items.append(item)
                    else:
                        raise JsonHttpError(f"invalid query value for {key}")
                normalized[key] = items
            else:
                raise JsonHttpError(f"invalid query value for {key}")
        return normalized or None

    def get_json(
        self,
        path: str,
        params: Mapping[str, object] | None = None,
    ) -> JsonHttpResponse:
        """GET and decode JSON, retrying transient failures.

        Returns:
            The decoded value together with its original bytes and final URL.

        Raises:
            JsonHttpError: If the endpoint remains unavailable or malformed.

        """
        request = self._client.build_request(
            "GET",
            path.lstrip("/"),
            params=self._query_params(params),
        )
        last_error: Exception | None = None
        for attempt in range(self.max_attempts):
            self._wait_for_request_slot()
            response: httpx.Response | None = None
            retryable = True
            try:
                response = self._client.send(request)
                response.raise_for_status()
                data = response.json()
            except httpx.HTTPStatusError as error:
                last_error = error
                retryable = (
                    error.response.status_code == 429
                    or error.response.status_code >= 500
                )
            except (httpx.RequestError, json.JSONDecodeError) as error:
                last_error = error
            else:
                return JsonHttpResponse(data, response.content, str(response.url))

            if not retryable or attempt + 1 == self.max_attempts:
                break
            delay = self._retry_delay(attempt, response)
            if response is not None and response.status_code == 429:
                self._postpone_requests(delay)
            self._sleeper(delay)

        raise JsonHttpError(f"GET {request.url} failed: {last_error}") from last_error
