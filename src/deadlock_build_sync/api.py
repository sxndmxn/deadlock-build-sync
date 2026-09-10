from __future__ import annotations

import operator
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Self, cast

from .api_models import (
    DEFAULT_API_BASE_URL,
    GAME_MODE,
    HERO_DURATION_BUCKETS,
    ApiError,
    HeroDurationStat,
    Patch,
    calculate_patch_content_sha256,
    normalize_patch_guid,
    parse_datetime,
    parse_duration_statistics,
)
from .http_client import JsonHttpClient, JsonHttpError
from .ranks import DEFAULT_RANK_RANGE, RankCatalog, RankRange
from .snapshot import (
    EpochBoundary,
    EpochSet,
    EvidenceRecorder,
    EvidenceUnit,
    MatchMode,
    OutcomePolicy,
    SnapshotManifest,
)
from .value_validation import object_rows

if TYPE_CHECKING:
    import httpx


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
        transport: httpx.BaseTransport | None = None,
    ) -> None:
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
        self._http = JsonHttpClient(
            base_url,
            timeout=timeout,
            max_attempts=3,
            transport=transport,
        )
        self._http.set_request_interval(0.31)
        self._declare_static_routes()

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Self:
        """Keep one HTTP connection pool open for an API workflow.

        Returns:
            This API client.

        """
        return self

    def __exit__(self, *_: object) -> None:
        """Close the HTTP connection pool after an API workflow."""
        self.close()

    def _declare_static_routes(self) -> None:
        declarations = {
            "/v1/assets/client-versions": (
                EvidenceUnit.ASSET,
                "available-client-version",
            ),
            "/v1/assets/heroes": (EvidenceUnit.ASSET, "hero-asset"),
            "/v1/assets/items": (EvidenceUnit.ASSET, "item-or-ability-asset"),
            "/v1/assets/build-tags": (EvidenceUnit.ASSET, "build-tag-asset"),
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
    def _normalized_parameters(params: dict[str, object] | None) -> dict[str, object]:
        return {
            key: str(value).lower() if isinstance(value, bool) else value
            for key, value in (params or {}).items()
            if value is not None
        }

    def get_json(self, path: str, params: dict[str, object] | None = None) -> object:
        normalized = self._normalized_parameters(params)
        try:
            response = self._http.get_json(path, normalized or None)
        except JsonHttpError as error:
            raise ApiError(str(error)) from error
        self.recorder.record(path, normalized, response.content)
        return response.data

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

    def _asset_parameters(self, **parameters: object) -> dict[str, object]:
        return {"client_version": self.resolve_client_version(), **parameters}

    def active_heroes(self) -> list[dict[str, object]]:
        data = self.get_json(
            "/v1/assets/heroes",
            self._asset_parameters(only_active=True),
        )
        rows = object_rows(data)
        if rows is None:
            raise ApiError("active heroes response was not a list")
        heroes = [
            hero
            for hero in rows
            if isinstance(hero.get("id"), int)
            and not hero.get("disabled", False)
            and not hero.get("in_development", False)
            and str(hero.get("game_mode") or GAME_MODE).casefold() == GAME_MODE
        ]
        return sorted(heroes, key=lambda hero: cast("int", hero["id"]))

    def items(self) -> list[dict[str, object]]:
        data = self.get_json("/v1/assets/items", self._asset_parameters())
        rows = object_rows(data)
        if rows is None:
            raise ApiError("items response was not a list")
        return [
            item
            for item in rows
            if str(item.get("game_mode") or GAME_MODE).casefold() == GAME_MODE
        ]

    def build_tags(self) -> list[dict[str, object]]:
        data = self.get_json("/v1/assets/build-tags", self._asset_parameters())
        rows = object_rows(data)
        if rows is None:
            raise ApiError("build-tag assets response was not a list")
        return rows

    def rank_catalog(self) -> RankCatalog:
        data = self.get_json("/v1/assets/ranks", self._asset_parameters())
        rows = object_rows(data)
        if rows is None:
            raise ApiError("rank assets response was not a list")
        catalog = RankCatalog.from_assets(rows)
        catalog.validate_range(self.rank_range)
        return catalog

    def current_patch(self) -> Patch:
        data = self.get_json("/v2/patches")
        if isinstance(data, dict):
            data = data.get("patches") or data.get("data")
        rows = object_rows(data)
        if rows is None:
            raise ApiError("patch response did not contain a patch list")
        candidates: list[tuple[datetime, dict[str, object]]] = []
        for row in rows:
            published_at = row.get("pub_date")
            if not isinstance(published_at, str):
                continue
            candidates.append((parse_datetime(published_at), row))
        if not candidates:
            raise ApiError("patch response did not contain a current patch")
        parsed, latest = max(candidates, key=operator.itemgetter(0))
        content = latest.get("content")
        return Patch(
            title=str(latest.get("title") or "Current patch"),
            start_timestamp=int(parsed.timestamp()),
            published_at=str(latest["pub_date"]),
            source=str(latest.get("source") or "unknown"),
            guid=normalize_patch_guid(latest.get("guid")),
            link=str(latest.get("link") or ""),
            content_sha256=calculate_patch_content_sha256(content),
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
        **parameters: object,
    ) -> dict[str, object]:
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
    ) -> list[dict[str, object]]:
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
        rows = object_rows(data)
        if rows is None:
            raise ApiError(f"item stats response for hero {hero_id} was not a list")
        return rows

    def ability_order_stats(
        self,
        *,
        hero_id: int,
        min_unix_timestamp: int,
        min_matches: int,
        include_item_ids: tuple[int, ...] = (),
    ) -> list[dict[str, object]]:
        data = self.get_json(
            "/v1/analytics/ability-order-stats",
            self._analytic_parameters(
                hero_id=hero_id,
                min_unix_timestamp=min_unix_timestamp,
                min_ability_upgrades=1,
                max_ability_upgrades=16,
                min_matches=min_matches,
                include_item_ids=list(include_item_ids) or None,
            ),
        )
        rows = object_rows(data)
        if rows is None:
            raise ApiError(
                f"ability order stats response for hero {hero_id} was not a list"
            )
        return rows

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
                resolved = parse_duration_statistics(
                    row, label, minimum, maximum_exclusive
                )
                if resolved is None:
                    continue
                hero_id, point = resolved
                curves.setdefault(hero_id, []).append(point)
        return {hero_id: tuple(points) for hero_id, points in curves.items()}

    def hero_counter_stats(
        self,
        *,
        min_unix_timestamp: int,
        same_lane: bool,
    ) -> list[dict[str, object]]:
        data = self.get_json(
            "/v1/analytics/hero-counter-stats",
            self._analytic_parameters(
                min_unix_timestamp=min_unix_timestamp,
                same_lane_filter=same_lane,
            ),
        )
        rows = object_rows(data)
        if rows is None:
            raise ApiError("counter stats response was not a list")
        return rows

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
        build_tags_sha256: str,
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
            build_tags_sha256=build_tags_sha256,
            patch=patch.as_dict(),
            epochs=self.epochs_for_patch(patch),
            outcome_policy=self.outcome_policy,
            outcome_policy_enforced=False,
            records=tuple(self.recorder.records),
            warnings=warnings,
        )
