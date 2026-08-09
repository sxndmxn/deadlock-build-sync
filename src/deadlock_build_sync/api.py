from __future__ import annotations

import hashlib
import json
import operator
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .ranks import DEFAULT_RANK_RANGE, RankCatalog, RankRange
from .snapshot import (
    EpochBoundary,
    EpochSet,
    EvidenceRecorder,
    EvidenceUnit,
    MatchMode,
    OutcomePolicy,
    SnapshotManifest,
    canonical_json,
    sha256_json,
)

DEFAULT_API_BASE_URL = "https://api.deadlock-api.com"
GAME_MODE = "normal"


class ApiError(RuntimeError):
    """Raised when deadlock-api.com returns invalid or unavailable data."""


@dataclass(frozen=True)
class Patch:
    title: str
    start_timestamp: int
    published_at: str
    source: str = "unknown"
    guid: str = "unknown"
    link: str = ""
    content_sha256: str = ""

    @property
    def identity(self) -> str:
        return sha256_json({
            "source": self.source,
            "guid": self.guid,
            "published_at": self.published_at,
            "link": self.link,
            "content_sha256": self.content_sha256,
        })

    def as_dict(self) -> dict[str, str | int]:
        return {
            "identity": self.identity,
            "title": self.title,
            "start_timestamp": self.start_timestamp,
            "published_at": self.published_at,
            "source": self.source,
            "guid": self.guid,
            "link": self.link,
            "content_sha256": self.content_sha256,
        }


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


# Domain intervals are half-open. The API currently accepts inclusive integer bounds,
# so max_duration_s - 1 is sent on the wire.
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


def _parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ApiError(f"invalid current patch timestamp: {value}") from error
    return parsed.replace(tzinfo=parsed.tzinfo or UTC)


def _patch_guid(value: object) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, (dict, list)):
        return canonical_json(value).decode()
    return "unknown"


class DeadlockApi:
    def __init__(
        self,
        base_url: str = DEFAULT_API_BASE_URL,
        timeout: float = 60.0,
        *,
        rank_range: RankRange = DEFAULT_RANK_RANGE,
        match_mode: MatchMode = MatchMode.RANKED,
        client_version: int | None = None,
        as_of_timestamp: int | None = None,
        epochs: EpochSet | None = None,
        recorder: EvidenceRecorder | None = None,
        outcome_policy: OutcomePolicy | None = None,
    ) -> None:
        parsed_url = urllib.parse.urlparse(base_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError("base URL must be an absolute HTTP(S) URL")
        if client_version is not None and client_version <= 0:
            raise ValueError("client version must be positive")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.rank_range = rank_range
        self.match_mode = match_mode
        self.requested_client_version = client_version
        self.client_version: int | None = None
        self.as_of_timestamp = as_of_timestamp or int(time.time())
        self.configured_epochs = epochs
        self.recorder = recorder or EvidenceRecorder()
        self.outcome_policy = outcome_policy or OutcomePolicy()
        self._declare_static_routes()

    def _declare_static_routes(self) -> None:
        declarations = {
            "/v1/assets/client-versions": (
                EvidenceUnit.ASSET,
                "available-client-version",
            ),
            "/v1/assets/heroes": (EvidenceUnit.ASSET, "hero-asset"),
            "/v1/assets/items": (EvidenceUnit.ASSET, "item-or-ability-asset"),
            "/v1/assets/ranks": (EvidenceUnit.ASSET, "rank-tier-asset"),
            "/v2/patches": (EvidenceUnit.ASSET, "patch-feed-entry"),
            "/v1/players/steam": (EvidenceUnit.ASSET, "steam-account-profile"),
            "/v1/analytics/ability-order-stats": (
                EvidenceUnit.ABILITY_PATH,
                "observed-ability-prefix",
            ),
            "/v1/analytics/hero-stats": (
                EvidenceUnit.HERO_APPEARANCE,
                "ending-duration-hero-appearance",
            ),
            "/v1/analytics/hero-counter-stats": (
                EvidenceUnit.HERO_ENEMY_PAIR,
                "hero-enemy-pair",
            ),
        }
        for path, (unit, grain) in declarations.items():
            self.recorder.declare(
                path,
                unit=unit,
                backend_grain=grain,
                fallback_behavior="reject; never change population or grain",
            )

    @staticmethod
    def _normalized_parameters(params: dict[str, Any] | None) -> dict[str, Any]:
        return {
            key: str(value).lower() if isinstance(value, bool) else value
            for key, value in (params or {}).items()
            if value is not None
        }

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        normalized = self._normalized_parameters(params)
        url = f"{self.base_url}{path}"
        if normalized:
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
                    raw = response.read()
                data = json.loads(raw)
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
            else:
                self.recorder.record(path, normalized, raw)
                return data
        raise ApiError(f"GET {url} failed: {last_error}") from last_error

    def resolve_client_version(self) -> int:
        if self.client_version is not None:
            return self.client_version
        data = self.get_json("/v1/assets/client-versions")
        if not isinstance(data, list):
            raise ApiError("client versions response was not a list")
        versions = sorted(version for version in data if isinstance(version, int))
        if not versions:
            raise ApiError("client versions response contained no versions")
        requested = self.requested_client_version
        if requested is not None and requested not in versions:
            raise ApiError(f"requested client version {requested} is unavailable")
        self.client_version = requested or versions[-1]
        return self.client_version

    def _asset_parameters(self, **parameters: Any) -> dict[str, Any]:
        return {"client_version": self.resolve_client_version(), **parameters}

    def active_heroes(self) -> list[dict[str, Any]]:
        data = self.get_json(
            "/v1/assets/heroes",
            self._asset_parameters(only_active=True),
        )
        if not isinstance(data, list):
            raise ApiError("active heroes response was not a list")
        heroes = [
            hero
            for hero in data
            if isinstance(hero, dict)
            and isinstance(hero.get("id"), int)
            and not hero.get("disabled", False)
            and not hero.get("in_development", False)
            and str(hero.get("game_mode") or GAME_MODE).casefold() == GAME_MODE
        ]
        return sorted(heroes, key=lambda hero: int(hero["id"]))

    def items(self) -> list[dict[str, Any]]:
        data = self.get_json("/v1/assets/items", self._asset_parameters())
        if not isinstance(data, list):
            raise ApiError("items response was not a list")
        return [
            item
            for item in data
            if isinstance(item, dict)
            and str(item.get("game_mode") or GAME_MODE).casefold() == GAME_MODE
        ]

    def rank_catalog(self) -> RankCatalog:
        data = self.get_json("/v1/assets/ranks", self._asset_parameters())
        if not isinstance(data, list):
            raise ApiError("rank assets response was not a list")
        catalog = RankCatalog.from_assets([
            row for row in data if isinstance(row, dict)
        ])
        catalog.validate_range(self.rank_range)
        return catalog

    def current_patch(self) -> Patch:
        data = self.get_json("/v2/patches")
        if isinstance(data, dict):
            data = data.get("patches") or data.get("data")
        if not isinstance(data, list):
            raise ApiError("patch response did not contain a patch list")
        candidates: list[tuple[datetime, dict[str, Any]]] = []
        for row in data:
            if not isinstance(row, dict) or not isinstance(row.get("pub_date"), str):
                continue
            candidates.append((_parse_datetime(row["pub_date"]), row))
        if not candidates:
            raise ApiError("patch response did not contain a current patch")
        parsed, latest = max(candidates, key=operator.itemgetter(0))
        content = latest.get("content")
        return Patch(
            title=str(latest.get("title") or "Current patch"),
            start_timestamp=int(parsed.timestamp()),
            published_at=str(latest["pub_date"]),
            source=str(latest.get("source") or "unknown"),
            guid=_patch_guid(latest.get("guid")),
            link=str(latest.get("link") or ""),
            content_sha256=hashlib.sha256(canonical_json(content)).hexdigest(),
        )

    def steam_persona(self, account_id: int) -> str:
        data = self.get_json("/v1/players/steam", {"account_ids": account_id})
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            raise ApiError(f"no Steam profile found for account {account_id}")
        persona = data[0].get("personaname")
        if not isinstance(persona, str) or not persona.strip():
            raise ApiError(f"Steam profile {account_id} did not contain a persona name")
        return persona.strip()

    def _analytic_parameters(
        self,
        *,
        min_unix_timestamp: int,
        **parameters: Any,
    ) -> dict[str, Any]:
        if min_unix_timestamp > self.as_of_timestamp:
            raise ApiError("analysis start is after the frozen as-of cutoff")
        return {
            "game_mode": GAME_MODE,
            "match_mode": self.match_mode.value,
            "min_unix_timestamp": min_unix_timestamp,
            "max_unix_timestamp": self.as_of_timestamp,
            **self.rank_range.api_parameters,
            **parameters,
        }

    def item_stats(
        self,
        *,
        hero_id: int,
        min_unix_timestamp: int,
        min_matches: int,
        bucket: str | None = None,
    ) -> list[dict[str, Any]]:
        grain = "purchase-event"
        if bucket:
            grain = f"purchase-event-by-{bucket}"
        self.recorder.declare(
            "/v1/analytics/item-stats",
            unit=EvidenceUnit.PURCHASE_EVENT,
            backend_grain=grain,
            fallback_behavior="reject; no adoption-rate substitution",
            warnings=(
                "matches counts purchase-event observations, not unique player matches",
            ),
        )
        data = self.get_json(
            "/v1/analytics/item-stats",
            self._analytic_parameters(
                hero_id=hero_id,
                min_unix_timestamp=min_unix_timestamp,
                min_matches=min_matches,
                bucket=bucket,
            ),
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
            self._analytic_parameters(
                hero_id=hero_id,
                min_unix_timestamp=min_unix_timestamp,
                min_ability_upgrades=1,
                max_ability_upgrades=16,
                min_matches=min_matches,
            ),
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
        for label, minimum, maximum_exclusive in HERO_DURATION_BUCKETS:
            data = self.get_json(
                "/v1/analytics/hero-stats",
                self._analytic_parameters(
                    min_unix_timestamp=min_unix_timestamp,
                    bucket="no_bucket",
                    min_duration_s=minimum,
                    max_duration_s=maximum_exclusive - 1,
                ),
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
                        min_duration_s=minimum,
                        max_duration_s=maximum_exclusive,
                        wins=wins,
                        losses=losses,
                        matches=matches,
                    )
                )
        return {hero_id: tuple(points) for hero_id, points in curves.items()}

    def hero_counter_stats(
        self,
        *,
        hero_id: int,
        min_unix_timestamp: int,
        same_lane: bool,
    ) -> list[dict[str, Any]]:
        data = self.get_json(
            "/v1/analytics/hero-counter-stats",
            self._analytic_parameters(
                hero_id=hero_id,
                min_unix_timestamp=min_unix_timestamp,
                same_lane_filter=same_lane,
            ),
        )
        if not isinstance(data, list):
            raise ApiError(f"counter stats response for hero {hero_id} was not a list")
        return [row for row in data if isinstance(row, dict)]

    def epochs_for_patch(self, patch: Patch) -> EpochSet:
        if self.configured_epochs is not None:
            return self.configured_epochs
        boundary = EpochBoundary(patch.identity, patch.start_timestamp)
        return EpochSet(
            mechanics=boundary,
            matchmaking=boundary,
            map_objectives=boundary,
            telemetry=boundary,
        )

    def analysis_start_timestamp(self, patch: Patch) -> int:
        return self.epochs_for_patch(patch).analysis_start_timestamp

    def snapshot_manifest(
        self,
        *,
        patch: Patch,
        rank_catalog: RankCatalog,
    ) -> SnapshotManifest:
        version = self.resolve_client_version()
        warnings = ()
        if self.configured_epochs is None:
            warnings = (
                "The public patch feed does not expose independent epoch feeds; all epoch boundaries default to the selected patch and remain separately fingerprinted.",
                "Public aggregate outcome routes cannot enforce every player-level eligibility exclusion; claims are descriptive-only.",
            )
        return SnapshotManifest(
            client_version=version,
            as_of_timestamp=self.as_of_timestamp,
            created_at=datetime.now(UTC).isoformat(),
            match_mode=self.match_mode,
            game_mode=GAME_MODE,
            rank_range=rank_catalog.range_dict(self.rank_range),
            rank_labels_sha256=rank_catalog.sha256,
            patch=patch.as_dict(),
            epochs=self.epochs_for_patch(patch),
            outcome_policy=self.outcome_policy,
            outcome_policy_enforced=False,
            records=tuple(self.recorder.records),
            warnings=warnings,
        )
