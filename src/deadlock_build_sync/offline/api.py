from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from deadlock_build_sync.http_client import JsonHttpClient, JsonHttpError

from .config import API_BASE_URL, Cohort, RunPaths, sha256_json

if TYPE_CHECKING:
    from pathlib import Path


class ApiError(RuntimeError):
    """Raised when a source request cannot be validated."""


class ApiClient:
    def __init__(self, base_url: str = API_BASE_URL, timeout: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._http = JsonHttpClient(
            base_url,
            timeout=timeout,
            max_attempts=5,
        )

    def close(self) -> None:
        self._http.close()

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        try:
            return self._http.get_json(path, params).data
        except JsonHttpError as error:
            raise ApiError(str(error)) from error


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, default=str)
        + "\n",
        encoding="utf-8",
    )


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def capture_sources(paths: RunPaths) -> dict[str, Any]:
    client = ApiClient()
    try:
        versions = client.get("/v1/assets/client-versions")
        valid_versions = sorted(
            version for version in versions if isinstance(version, int)
        )
        if not valid_versions:
            raise ApiError("client-version response contained no numeric version")
        client_version = valid_versions[-1]
        params = {"client_version": client_version}
        heroes = client.get("/v1/assets/heroes", {**params, "only_active": True})
        items = client.get("/v1/assets/items", params)
        ranks = client.get("/v1/assets/ranks", params)
        patches = client.get("/v2/patches")
        openapi = client.get("/openapi.json")
    finally:
        client.close()

    active_heroes = sorted(
        (
            hero
            for hero in heroes
            if isinstance(hero, dict)
            and isinstance(hero.get("id"), int)
            and not hero.get("disabled", False)
            and not hero.get("in_development", False)
            and str(hero.get("game_mode") or "normal").casefold() == "normal"
        ),
        key=lambda row: int(row["id"]),
    )
    shop_items = sorted(
        (
            item
            for item in items
            if isinstance(item, dict)
            and isinstance(item.get("id"), int)
            and item.get("type") == "upgrade"
            and item.get("shopable")
            and not item.get("disabled", False)
            and isinstance(item.get("item_tier"), int)
            and 1 <= int(item["item_tier"]) <= 4
        ),
        key=lambda row: int(row["id"]),
    )
    payloads = {
        "client_versions.json": versions,
        "heroes.json": active_heroes,
        "items-all.json": items,
        "items.json": shop_items,
        "ranks.json": ranks,
        "patches.json": patches,
        "openapi.json": openapi,
    }
    for name, payload in payloads.items():
        write_json(paths.raw / name, payload)
    return {
        "client_version": client_version,
        "active_heroes": len(active_heroes),
        "shop_items": len(shop_items),
        "source_sha256": {name: sha256_json(value) for name, value in payloads.items()},
    }


def _analytics_params(cohort: Cohort, hero_id: int) -> dict[str, Any]:
    return {
        "game_mode": "normal",
        "match_mode": "ranked",
        "hero_id": hero_id,
        "min_unix_timestamp": int(cohort.since.timestamp()),
        "max_unix_timestamp": int(cohort.resolved_as_of().timestamp()),
        "min_average_badge": cohort.minimum_badge,
        "max_average_badge": cohort.maximum_badge,
        "min_matches": 20,
    }


def capture_api_audit(paths: RunPaths, cohort: Cohort) -> dict[str, Any]:
    heroes = read_json(paths.raw / "heroes.json")
    client = ApiClient()
    failures: list[dict[str, Any]] = []
    calls = 0
    try:
        for index, hero in enumerate(heroes, start=1):
            hero_id = int(hero["id"])
            params = _analytics_params(cohort, hero_id)
            requests = (
                ("item-stats", "/v1/analytics/item-stats", params),
                (
                    "item-flow-stats",
                    "/v1/analytics/item-flow-stats",
                    {**params, "hero_ids": hero_id, "hero_id": None},
                ),
            )
            for label, endpoint, request_params in requests:
                target = paths.api / f"hero-{hero_id}-{label}.json"
                try:
                    write_json(target, client.get(endpoint, request_params))
                    calls += 1
                except ApiError as error:
                    failures.append({
                        "hero_id": hero_id,
                        "endpoint": endpoint,
                        "error": str(error),
                    })
            if index % 10 == 0:
                print(f"API audit: {index}/{len(heroes)} heroes", flush=True)
        duration_buckets = (
            ("under-25m", 0, 1499),
            ("25-30m", 1500, 1799),
            ("30-35m", 1800, 2099),
            ("35-40m", 2100, 2399),
            ("40-45m", 2400, 2699),
            ("45-50m", 2700, 2999),
            ("50m-plus", 3000, 6999),
        )
        base = _analytics_params(cohort, int(heroes[0]["id"]))
        base.pop("hero_id")
        for label, minimum, maximum in duration_buckets:
            target = paths.api / f"hero-duration-{label}.json"
            try:
                write_json(
                    target,
                    client.get(
                        "/v1/analytics/hero-stats",
                        {
                            **base,
                            "bucket": "no_bucket",
                            "min_duration_s": minimum,
                            "max_duration_s": maximum,
                        },
                    ),
                )
                calls += 1
            except ApiError as error:
                failures.append({
                    "duration_bucket": label,
                    "endpoint": "/v1/analytics/hero-stats",
                    "error": str(error),
                })
    finally:
        client.close()
    write_json(paths.api / "failures.json", failures)
    return {"calls": calls, "failures": failures}
