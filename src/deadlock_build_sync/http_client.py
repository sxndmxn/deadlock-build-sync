from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Self

import httpx

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping


class JsonHttpError(RuntimeError):
    """Raised when a JSON endpoint remains unavailable or invalid."""


@dataclass(frozen=True)
class JsonHttpResponse:
    """A decoded JSON response with the original evidence bytes."""

    data: Any
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

    def get_json(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
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
            params=params,
        )
        last_error: Exception | None = None
        for attempt in range(self.max_attempts):
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
            self._sleeper(self._retry_delay(attempt, response))

        raise JsonHttpError(f"GET {request.url} failed: {last_error}") from last_error
