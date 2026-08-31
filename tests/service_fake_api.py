from datetime import UTC, datetime
from typing import override

from deadlock_build_sync.api import (
    HERO_DURATION_BUCKETS,
    DeadlockApi,
    HeroDurationStat,
    Patch,
)
from deadlock_build_sync.ranks import RankCatalog
from deadlock_build_sync.snapshot import (
    EpochBoundary,
    EpochSet,
    EvidenceRecord,
    EvidenceUnit,
    MatchMode,
    OutcomePolicy,
    SnapshotManifest,
)
from deadlock_build_sync.value_validation import (
    integer,
)


class FakeApi(DeadlockApi):
    def __init__(
        self,
        *,
        ability_rows: list[dict[str, object]],
        duration_points: tuple[HeroDurationStat, ...],
    ) -> None:
        super().__init__(client_version=123, as_of_timestamp=999)
        self.client_version = 123
        self._ability_rows = ability_rows
        self._duration_points = duration_points
        self.counter_stat_calls: list[bool] = []
        self.ability_filter_calls: list[tuple[int, ...]] = []
        self._hero: dict[str, object] = {
            "id": 12,
            "name": "Kelvin",
            "class_name": "hero_kelvin",
            "items": {f"signature{slot}": f"ability_{slot}" for slot in range(1, 5)},
            "description": {
                "lore": "Lore",
                "role": "Protect allies",
                "playstyle": "Control space.",
            },
            "level_info": {
                str(level): {
                    "bonus_currencies": [
                        (
                            "EAbilityUnlocks"
                            if level in {1, 3, 5, 8}
                            else "EAbilityPoints"
                        )
                    ]
                }
                for level in range(1, 37)
            },
        }
        self._assets: list[dict[str, object]] = [
            {
                "id": tier * 100 + index,
                "name": f"Tier {tier} Item {index}",
                "class_name": f"item_{tier}_{index}",
                "cost": tier * 500,
                "component_items": [],
                "item_tier": tier,
                "item_slot_type": "spirit",
                "shopable": True,
                "disabled": False,
                "shop_image_webp": "https://example.invalid/item.webp",
                **(
                    {"description": {"desc": "Applies healing reduction."}}
                    if tier == 1 and index == 3
                    else (
                        {"description": {"desc": "Increases weapon damage."}}
                        if tier == 1 and index in {0, 1}
                        else {"description": {"desc": "Gain Spirit Power."}}
                    )
                ),
            }
            for tier in range(1, 5)
            for index in range(10)
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
    def resolve_client_version(self) -> int:
        return 123

    @override
    def rank_catalog(self) -> RankCatalog:
        return RankCatalog({
            1: "Initiate",
            2: "Seeker",
            3: "Acolyte",
            4: "Sentinel",
            5: "Mystic",
            6: "Ritualist",
            7: "Emissary",
            8: "Oracle",
            9: "Phantom",
            10: "Ascendant",
            11: "Eternus",
        })

    @override
    def active_heroes(self) -> list[dict[str, object]]:
        return [self._hero]

    @override
    def items(self) -> list[dict[str, object]]:
        return self._assets

    @override
    def build_tags(self) -> list[dict[str, object]]:
        classes = (
            "weapon",
            "spirit",
            "vitality",
            "damage",
            "utility",
            "healing",
            "crowd_control",
            "mobility",
            "melee",
            "headshots",
            "debuff",
            "complexity_1",
            "complexity_2",
            "complexity_3",
        )
        return [
            {
                "id": index,
                "class_name": f"citadel_build_tag_{class_name}",
                "label": class_name.replace("_", " ").title(),
            }
            for index, class_name in enumerate(classes, start=1)
        ]

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
    ) -> list[dict[str, object]]:
        _ = hero_id, min_unix_timestamp, min_matches
        return [
            {
                "item_id": integer(asset["id"]),
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
        include_item_ids: tuple[int, ...] = (),
    ) -> list[dict[str, object]]:
        _ = hero_id, min_unix_timestamp, min_matches
        self.ability_filter_calls.append(include_item_ids)
        return self._ability_rows

    @override
    def hero_stats_by_duration(
        self,
        *,
        min_unix_timestamp: int,
    ) -> dict[int, tuple[HeroDurationStat, ...]]:
        _ = min_unix_timestamp
        return {12: self._duration_points}

    @override
    def hero_counter_stats(
        self,
        *,
        min_unix_timestamp: int,
        same_lane: bool,
    ) -> list[dict[str, object]]:
        _ = min_unix_timestamp
        self.counter_stat_calls.append(same_lane)
        return [
            {
                "hero_id": 12,
                "enemy_hero_id": 1,
                "matches": 100,
                "wins": 50,
                "same_lane": same_lane,
            },
            {
                "hero_id": 99,
                "enemy_hero_id": 12,
                "matches": 90,
                "wins": 40,
                "same_lane": same_lane,
            },
        ]

    @override
    def snapshot_manifest(
        self,
        *,
        patch: Patch,
        rank_catalog: RankCatalog,
        build_tags_sha256: str,
    ) -> SnapshotManifest:
        boundary = EpochBoundary("patch", patch.start_timestamp)
        record = EvidenceRecord(
            path="fixture",
            parameters={},
            fetched_at=datetime.now(UTC).isoformat(),
            sha256="0" * 64,
            byte_count=1,
            unit=EvidenceUnit.ASSET,
            backend_grain="fixture",
            fallback_behavior="none",
        )
        return SnapshotManifest(
            client_version=123,
            as_of_timestamp=999,
            created_at=datetime.now(UTC).isoformat(),
            match_mode=MatchMode.RANKED,
            game_mode="normal",
            rank_range=rank_catalog.range_dict(self.rank_range),
            rank_labels_sha256=rank_catalog.sha256,
            build_tags_sha256=build_tags_sha256,
            patch=patch.as_dict(),
            epochs=EpochSet(boundary, boundary, boundary, boundary),
            outcome_policy=OutcomePolicy(),
            outcome_policy_enforced=False,
            records=(record,),
        )


def ability_rows() -> list[dict[str, object]]:
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
