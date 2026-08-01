from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .ranks import DEFAULT_RANK_RANGE, RankRange

DEFAULT_API_BASE_URL = "https://api.deadlock-api.com"


class ApiError(RuntimeError):
    """Raised when deadlock-api.com returns invalid or unavailable data."""


@dataclass(frozen=True)
class Patch:
    title: str
    start_timestamp: int
    published_at: str


@dataclass(frozen=True)
class HeroDurationStat:
    label: str
    min_duration_s: int
    max_duration_s: int
    wins: int
    losses: int
    matches: int

    @property
    def win_rate(self) -> float:
        return self.wins / self.matches if self.matches else 0.0


HERO_DURATION_BUCKETS = (
    ("<25m", 0, 1500),
    ("25–30m", 1500, 1800),
    ("30–35m", 1800, 2100),
    ("35–40m", 2100, 2400),
    ("40–45m", 2400, 2700),
    ("45–50m", 2700, 3000),
    ("50m+", 3000, 7000),
)
MIN_HERO_DURATION_MATCHES = 20


class DeadlockApi:
    def __init__(
        self,
        base_url: str = DEFAULT_API_BASE_URL,
        timeout: float = 60.0,
        *,
        rank_range: RankRange = DEFAULT_RANK_RANGE,
    ) -> None:
        parsed_url = urllib.parse.urlparse(base_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError("base URL must be an absolute HTTP(S) URL")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.rank_range = rank_range

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        if params:
            normalized = {
                key: str(value).lower() if isinstance(value, bool) else value
                for key, value in params.items()
                if value is not None
            }
            url = f"{url}?{urllib.parse.urlencode(normalized, doseq=True)}"

        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "deadlock-build-sync/0.1",
            },
        )
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.load(response)
            except (
                urllib.error.HTTPError,
                urllib.error.URLError,
                TimeoutError,
                json.JSONDecodeError,
            ) as error:
                last_error = error
                if (
                    isinstance(error, urllib.error.HTTPError)
                    and error.code < 500
                    and error.code != 429
                ):
                    break
                if attempt < 2:
                    time.sleep(2**attempt)
        raise ApiError(f"GET {url} failed: {last_error}") from last_error

    def active_heroes(self) -> list[dict[str, Any]]:
        data = self.get_json("/v1/assets/heroes", {"only_active": True})
        if not isinstance(data, list):
            raise ApiError("active heroes response was not a list")
        heroes = [
            hero
            for hero in data
            if isinstance(hero, dict)
            and isinstance(hero.get("id"), int)
            and not hero.get("disabled", False)
            and not hero.get("in_development", False)
        ]
        return sorted(heroes, key=lambda hero: int(hero["id"]))

    def items(self) -> list[dict[str, Any]]:
        data = self.get_json("/v1/assets/items")
        if not isinstance(data, list):
            raise ApiError("items response was not a list")
        return [item for item in data if isinstance(item, dict)]

    def current_patch(self) -> Patch:
        data = self.get_json("/v1/patches")
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            raise ApiError("patch response did not contain a current patch")
        first = data[0]
        published_at = first.get("pub_date")
        if not isinstance(published_at, str):
            raise ApiError("current patch did not contain pub_date")
        try:
            parsed = datetime.fromisoformat(published_at)
        except ValueError as error:
            raise ApiError(
                f"invalid current patch timestamp: {published_at}"
            ) from error
        return Patch(
            title=str(first.get("title") or "Current patch"),
            start_timestamp=int(parsed.timestamp()),
            published_at=published_at,
        )

    def steam_persona(self, account_id: int) -> str:
        data = self.get_json("/v1/players/steam", {"account_ids": account_id})
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            raise ApiError(f"no Steam profile found for account {account_id}")
        persona = data[0].get("personaname")
        if not isinstance(persona, str) or not persona.strip():
            raise ApiError(f"Steam profile {account_id} did not contain a persona name")
        return persona.strip()

    def item_stats(
        self,
        *,
        hero_id: int,
        min_unix_timestamp: int,
        min_matches: int,
        bucket: str | None = None,
    ) -> list[dict[str, Any]]:
        data = self.get_json(
            "/v1/analytics/item-stats",
            {
                "hero_id": hero_id,
                "game_mode": "normal",
                "min_unix_timestamp": min_unix_timestamp,
                "min_matches": min_matches,
                "bucket": bucket,
                **self.rank_range.api_parameters,
            },
        )
        if not isinstance(data, list):
            raise ApiError(f"item stats response for hero {hero_id} was not a list")
        return [row for row in data if isinstance(row, dict)]

    def ability_order_stats(
        self,
        *,
        hero_id: int,
        min_unix_timestamp: int,
        min_matches: int,
    ) -> list[dict[str, Any]]:
        data = self.get_json(
            "/v1/analytics/ability-order-stats",
            {
                "hero_id": hero_id,
                "game_mode": "normal",
                "min_unix_timestamp": min_unix_timestamp,
                "min_ability_upgrades": 16,
                "max_ability_upgrades": 16,
                "min_matches": min_matches,
                **self.rank_range.api_parameters,
            },
        )
        if not isinstance(data, list):
            raise ApiError(
                f"ability order stats response for hero {hero_id} was not a list"
            )
        return [row for row in data if isinstance(row, dict)]

    def hero_stats_by_duration(
        self,
        *,
        min_unix_timestamp: int,
    ) -> dict[int, tuple[HeroDurationStat, ...]]:
        curves: dict[int, list[HeroDurationStat]] = {}
        for label, min_duration_s, max_duration_s in HERO_DURATION_BUCKETS:
            data = self.get_json(
                "/v1/analytics/hero-stats",
                {
                    "bucket": "no_bucket",
                    "game_mode": "normal",
                    "min_unix_timestamp": min_unix_timestamp,
                    "min_duration_s": min_duration_s,
                    "max_duration_s": max_duration_s,
                    **self.rank_range.api_parameters,
                },
            )
            if not isinstance(data, list):
                raise ApiError(
                    f"hero duration stats response for {label} was not a list"
                )
            for row in data:
                if not isinstance(row, dict) or not isinstance(row.get("hero_id"), int):
                    continue
                matches = int(row.get("matches") or 0)
                wins = int(row.get("wins") or 0)
                losses = int(row.get("losses") or 0)
                if matches < MIN_HERO_DURATION_MATCHES or wins + losses != matches:
                    continue
                hero_id = int(row["hero_id"])
                curves.setdefault(hero_id, []).append(
                    HeroDurationStat(
                        label=label,
                        min_duration_s=min_duration_s,
                        max_duration_s=max_duration_s,
                        wins=wins,
                        losses=losses,
                        matches=matches,
                    )
                )
        return {hero_id: tuple(points) for hero_id, points in curves.items()}
