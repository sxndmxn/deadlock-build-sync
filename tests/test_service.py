from typing import Any, override

import pytest

from deadlock_build_sync.api import (
    HERO_DURATION_BUCKETS,
    DeadlockApi,
    HeroDurationStat,
    Patch,
)
from deadlock_build_sync.service import GuideError, generate_guides


class FakeApi(DeadlockApi):
    def __init__(
        self,
        *,
        ability_rows: list[dict[str, Any]],
        duration_points: tuple[HeroDurationStat, ...],
    ) -> None:
        super().__init__()
        self._ability_rows = ability_rows
        self._duration_points = duration_points
        self._hero: dict[str, Any] = {
            "id": 12,
            "name": "Kelvin",
            "class_name": "hero_kelvin",
            "items": {f"signature{slot}": f"ability_{slot}" for slot in range(1, 5)},
        }
        self._assets: list[dict[str, Any]] = [
            {
                "id": tier * 100 + index,
                "name": f"Tier {tier} Item {index}",
                "item_tier": tier,
                "item_slot_type": "spirit",
                "shopable": True,
                "disabled": False,
                "shop_image_webp": "https://example.invalid/item.webp",
            }
            for tier in range(1, 5)
            for index in range(8)
        ] + [
            {
                "id": slot * 10,
                "name": f"Ability {slot}",
                "class_name": f"ability_{slot}",
                "type": "ability",
                "ability_type": "signature",
                "description": {"desc": f"Ability {slot} description."},
            }
            for slot in range(1, 5)
        ]

    @override
    def active_heroes(self) -> list[dict[str, Any]]:
        return [self._hero]

    @override
    def items(self) -> list[dict[str, Any]]:
        return self._assets

    @override
    def current_patch(self) -> Patch:
        return Patch("Patch", 123, "2026-01-01T00:00:00Z")

    @override
    def steam_persona(self, account_id: int) -> str:
        _ = account_id
        return "Player"

    @override
    def item_stats(
        self,
        *,
        hero_id: int,
        min_unix_timestamp: int,
        min_matches: int,
        bucket: str | None = None,
    ) -> list[dict[str, Any]]:
        _ = hero_id, min_unix_timestamp, min_matches
        return [
            {
                "item_id": int(asset["id"]),
                "matches": 100,
                "wins": 60,
                **({"bucket": 1000} if bucket is not None else {}),
            }
            for asset in self._assets
            if asset.get("shopable")
        ]

    @override
    def ability_order_stats(
        self,
        *,
        hero_id: int,
        min_unix_timestamp: int,
        min_matches: int,
    ) -> list[dict[str, Any]]:
        _ = hero_id, min_unix_timestamp, min_matches
        return self._ability_rows

    @override
    def hero_stats_by_duration(
        self,
        *,
        min_unix_timestamp: int,
    ) -> dict[int, tuple[HeroDurationStat, ...]]:
        _ = min_unix_timestamp
        return {12: self._duration_points}


def ability_rows() -> list[dict[str, Any]]:
    return [
        {
            "abilities": [10, 20, 30, 40] * 4,
            "matches": 100,
            "wins": 60,
            "losses": 40,
        }
    ]


def duration_points() -> tuple[HeroDurationStat, ...]:
    return tuple(
        HeroDurationStat(label, minimum, maximum, 55, 45, 100)
        for label, minimum, maximum in HERO_DURATION_BUCKETS
    )


def test_rejects_selected_hero_without_complete_ability_path() -> None:
    api = FakeApi(ability_rows=[], duration_points=duration_points())

    with pytest.raises(GuideError, match="complete 16-step ability path"):
        generate_guides(
            api,
            account_id=123,
            hero_query="Kelvin",
            all_heroes=False,
        )


def test_skips_all_hero_with_incomplete_duration_curve() -> None:
    api = FakeApi(
        ability_rows=ability_rows(),
        duration_points=duration_points()[1:],
    )

    generated = generate_guides(
        api,
        account_id=123,
        hero_query=None,
        all_heroes=True,
    )

    assert not generated.guides
    assert not generated.contexts
    assert generated.skipped_heroes == ("Kelvin (a complete reliable duration curve)",)
