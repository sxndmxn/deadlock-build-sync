"""Reuse identical API responses during exploratory guide comparisons."""

from __future__ import annotations

import hashlib
import json
import time
from threading import Lock
from typing import TYPE_CHECKING, override

import httpx

from deadlock_build_sync.artifacts import atomic_write_bytes, atomic_write_json

if TYPE_CHECKING:
    from pathlib import Path


class SnapshotTransport(httpx.BaseTransport):
    def __init__(self, raw: Path, cache: Path) -> None:
        self.raw = raw
        self.cache = cache
        self.cache.mkdir(parents=True, exist_ok=True)
        self.transport: httpx.BaseTransport = httpx.HTTPTransport(retries=2)
        self.lock = Lock()
        self.next_request_at = 0.0

    @override
    def handle_request(self, request: httpx.Request) -> httpx.Response:
        assets = {
            "/v1/assets/client-versions": "client_versions.json",
            "/v1/assets/heroes": "heroes.json",
            "/v1/assets/items": "items-all.json",
            "/v1/assets/ranks": "ranks.json",
            "/v2/patches": "patches.json",
        }
        if request.url.path in assets:
            content = (self.raw / assets[request.url.path]).read_bytes()
        else:
            key = hashlib.sha256(str(request.url).encode()).hexdigest()
            path = self.cache / f"{key}.json"
            if path.exists():
                content = path.read_bytes()
                metadata = json.loads(
                    (self.cache / f"{key}.request.json").read_text(encoding="utf-8")
                )
                if metadata != {
                    "url": str(request.url),
                    "response_sha256": hashlib.sha256(content).hexdigest(),
                }:
                    raise ValueError(
                        "Cached comparison response differs from its fingerprint"
                    )
            else:
                response = self.fetch_response(request)
                if response.status_code != 200:
                    return response
                content = response.content
                json.loads(content)
                atomic_write_bytes(path, content)
                atomic_write_json(
                    self.cache / f"{key}.request.json",
                    {
                        "url": str(request.url),
                        "response_sha256": hashlib.sha256(content).hexdigest(),
                    },
                )
        return httpx.Response(200, content=content, request=request)

    def fetch_response(self, request: httpx.Request) -> httpx.Response:
        with self.lock:
            delay = max(0, self.next_request_at - time.monotonic())
            time.sleep(delay)
            response = self.transport.handle_request(request)
            response.read()
            delay = 1.1
            if response.status_code == 429:
                try:
                    delay = max(30.0, float(response.headers.get("retry-after", "30")))
                except ValueError:
                    delay = 30.0
            self.next_request_at = time.monotonic() + delay
            return response

    @override
    def close(self) -> None:
        self.transport.close()
