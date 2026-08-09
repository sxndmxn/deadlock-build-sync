from datetime import UTC, datetime
from typing import Any, override

import pytest

from deadlock_build_sync.api import (
    HERO_DURATION_BUCKETS,
    DeadlockApi,
    HeroDurationStat,
    Patch,
)
from deadlock_build_sync.ranks import RankCatalog
from deadlock_build_sync.service import GuideError, generate_guides
from deadlock_build_sync.snapshot import (
    EpochBoundary,
    EpochSet,
    EvidenceRecord,
    EvidenceUnit,
    MatchMode,
    OutcomePolicy,
    SnapshotManifest,
)


class FakeApi(DeadlockApi):
    def __init__(
        self,
        *,
        ability_rows: list[dict[str, Any]],
        duration_points: tuple[HeroDurationStat, ...],
    ) -> None:
        super().__init__(client_version=123, as_of_timestamp=999)
        self.client_version = 123
        self._ability_rows = ability_rows
        self._duration_points = duration_points
        self._hero: dict[str, Any] = {
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
        self._assets: list[dict[str, Any]] = [
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

    @override
    def hero_counter_stats(
        self,
        *,
        hero_id: int,
        min_unix_timestamp: int,
        same_lane: bool,
    ) -> list[dict[str, Any]]:
        _ = hero_id, min_unix_timestamp
        return [
            {"enemy_hero_id": 1, "matches": 100, "wins": 50, "same_lane": same_lane}
        ]

    @override
    def snapshot_manifest(
        self,
        *,
        patch: Patch,
        rank_catalog: RankCatalog,
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
            patch=patch.as_dict(),
            epochs=EpochSet(boundary, boundary, boundary, boundary),
            outcome_policy=OutcomePolicy(),
            outcome_policy_enforced=False,
            records=(record,),
        )


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

    with pytest.raises(GuideError, match="reached-state ability projection"):
        generate_guides(
            api,
            account_id=123,
            hero_query="Kelvin",
            all_heroes=False,
        )


def test_incomplete_duration_curve_abstains_without_discarding_policy() -> None:
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

    assert len(generated.guides) == 1
    assert generated.skipped_heroes == ()
    ending = generated.contexts[0]["ending_duration_profile"]
    assert ending["status"] == "abstained"
    assert ending["strongest_phase"] == "UNAVAILABLE"
    assert any(
        "ending-duration profile" in abstention.detail
        for abstention in generated.policies[0].abstentions
    )


def test_generated_guide_is_snapshot_bound_policy_projection() -> None:
    generated = generate_guides(
        FakeApi(ability_rows=ability_rows(), duration_points=duration_points()),
        account_id=123,
        hero_query="Kelvin",
        all_heroes=False,
    )

    assert len(generated.guides) == len(generated.policies) == 1
    guide = generated.guides[0]
    policy = generated.policies[0]
    assert guide.snapshot_id == generated.manifest.snapshot_id
    assert guide.policy_id == policy.policy_id
    assert len(policy.ability_plan) == 16
    assert all(node.kind.value == "ability" for node in policy.ability_plan)
    assert policy.nodes[0].kind.value in {"purchase", "choice"}
    assert {abstention.reason.value for abstention in policy.abstentions} == {
        "inadequate_support_or_overlap",
        "telemetry_failure",
        "unclear_threat",
    }
    assert guide.categories[0].name == "CORE — DEFAULT QUEUE"
    assert not guide.categories[0].optional
    assert generated.contexts[0]["ending_duration_profile"]["estimand"] == (
        "ending_duration_profile"
    )
    assert (
        generated.contexts[0]["ability_policy"]["steps"][0]["earliest_legal_level"] == 1
    )
