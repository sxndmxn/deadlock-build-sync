from datetime import UTC, datetime
from typing import Any, override

import pytest

from deadlock_build_sync.api import (
    HERO_DURATION_BUCKETS,
    DeadlockApi,
    HeroDurationStat,
    Patch,
)
from deadlock_build_sync.build_evidence import (
    BuildEvidenceCatalog,
    CoreCandidate,
    HeroBuildEvidence,
    ItemEvidence,
    SequencePolicy,
    SequenceTransition,
    SituationalBranch,
    SituationalPolicy,
)
from deadlock_build_sync.policy import BuildPolicy
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
    sha256_json,
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
                **(
                    {"description": {"desc": "Applies healing reduction."}}
                    if tier == 1 and index == 3
                    else {}
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
    def active_heroes(self) -> list[dict[str, Any]]:
        return [self._hero]

    @override
    def items(self) -> list[dict[str, Any]]:
        return self._assets

    @override
    def build_tags(self) -> list[dict[str, Any]]:
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


def build_evidence(
    api: FakeApi,
    *,
    with_situational_branch: bool = False,
    with_component_path: bool = False,
) -> BuildEvidenceCatalog:
    eligible = 100
    item_rows = tuple(
        ItemEvidence(
            item_id=int(asset["id"]),
            item=str(asset["name"]),
            tier=int(asset["item_tier"]),
            cost=int(asset["cost"]),
            slot=str(asset["item_slot_type"]),
            active=False,
            adopter_matches=90 - int(asset["id"]) % 100,
            eligible_player_matches=eligible,
            purchase_events=100,
            wins=50,
            adoption=(90 - int(asset["id"]) % 100) / eligible,
            observed_outcome_rate=50 / (90 - int(asset["id"]) % 100),
            median_buy_time_s=float(asset["id"]),
            median_valid_buy_net_worth=float(asset["id"] * 10),
            buy_net_worth_q25=float(asset["id"] * 9),
            buy_net_worth_q75=float(asset["id"] * 11),
            valid_buy_net_worth_share=0.9,
        )
        for asset in api.items()
        if asset.get("shopable")
    )
    situational = (
        SituationalPolicy(
            branches=(
                SituationalBranch(
                    threat="healing",
                    item_id=103,
                    enemy_hero_id=7,
                    mechanic_ref="item/103/healing",
                    comparator="same-opportunity item 104 or save",
                    comparator_item_id=104,
                    comparison_support=30,
                    same_opportunity=True,
                    support=40,
                    effective_support=30.0,
                    overlap=0.8,
                    stable=True,
                    comparative_interval=(0.01, 0.06),
                    trigger="Enemy hero 7 presents material healing.",
                    replacement="Choose item 103 instead of item 104.",
                    execution="Use the verified healing response while observed.",
                    failure_condition="Skip when healing is not material.",
                ),
            ),
            abstentions=("One weaker candidate failed the overlap gate.",),
        )
        if with_situational_branch
        else None
    )
    hero = HeroBuildEvidence(
        hero_id=12,
        hero="Kelvin",
        eligible_player_matches=eligible,
        median_final_net_worth=20_000,
        core_candidates=(CoreCandidate((100, 101, 200, 201, 300, 301, 400, 401), 40),),
        items=item_rows,
        sequence_policy=(
            SequencePolicy(
                (100, 101, 102, 200, 201, 300, 301, 400, 401),
                (SequenceTransition("popularity", 0, 0, 0, 100, 40, 100),),
                20,
                "deterministic_backoff",
                {"chronological_fold": "test"},
                {"evaluated": True, "passed": False, "promoted": False},
            )
            if with_component_path
            else None
        ),
        situational_policy=situational,
    )
    patch = api.current_patch()
    catalog = api.rank_catalog()
    heroes = api.active_heroes()
    assets = api.items()
    return BuildEvidenceCatalog(
        artifact_id="a" * 64,
        client_version=123,
        patch={"identity": patch.identity},
        cohort={
            "as_of": datetime.fromtimestamp(api.as_of_timestamp, UTC).isoformat(),
            "match_mode": "ranked",
            "game_mode": "normal",
            "minimum_badge": 71,
            "maximum_badge": 115,
        },
        epochs=api.epochs_for_patch(patch),
        rank_labels_sha256=catalog.sha256,
        heroes_sha256=sha256_json(heroes),
        items_sha256=sha256_json(assets),
        requested_hero_ids=frozenset({12}),
        heroes={12: hero},
        raw_bytes=b"fixture-build-evidence",
    )


def test_rejects_selected_hero_without_complete_ability_path() -> None:
    api = FakeApi(ability_rows=[], duration_points=duration_points())

    with pytest.raises(GuideError, match="reached-state ability projection"):
        generate_guides(
            api,
            build_evidence=build_evidence(api),
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
        build_evidence=build_evidence(api),
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
    api = FakeApi(ability_rows=ability_rows(), duration_points=duration_points())
    generated = generate_guides(
        api,
        build_evidence=build_evidence(api),
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
    assert [category.name for category in guide.categories] == [
        "CORE ITEMS",
        "TIER 1",
        "TIER 2",
        "TIER 3",
        "TIER 4",
    ]
    assert [len(category.items) for category in guide.categories] == [8, 8, 8, 8, 8]
    assert guide.item_count == 40
    assert not guide.categories[0].optional
    assert generated.contexts[0]["ending_duration_profile"]["estimand"] == (
        "ending_duration_profile"
    )
    assert (
        generated.contexts[0]["ability_policy"]["steps"][0]["earliest_legal_level"] == 1
    )


def test_required_components_join_core_queue_and_leave_optional_rows() -> None:
    api = FakeApi(ability_rows=ability_rows(), duration_points=duration_points())
    parent = next(item for item in api._assets if item.get("id") == 200)
    parent["component_items"] = ["item_1_2"]

    generated = generate_guides(
        api,
        build_evidence=build_evidence(api, with_component_path=True),
        account_id=123,
        hero_query="Kelvin",
        all_heroes=False,
    )

    guide = generated.guides[0]
    assert [item.item_id for item in guide.categories[0].items] == [
        100,
        101,
        102,
        200,
        201,
        300,
        301,
        400,
        401,
    ]
    assert [item.item_id for item in guide.core_items] == [
        100,
        101,
        200,
        201,
        300,
        301,
        400,
        401,
    ]
    assert 102 not in {item.item_id for item in guide.categories[1].items}
    assert (
        generated.contexts[0]["projection"]["categories"][0]["items"][2]["item_id"]
        == 102
    )


def test_admitted_situational_branch_reaches_policy_sidecar_and_tier_card() -> None:
    api = FakeApi(ability_rows=ability_rows(), duration_points=duration_points())
    generated = generate_guides(
        api,
        build_evidence=build_evidence(api, with_situational_branch=True),
        account_id=123,
        hero_query="Kelvin",
        all_heroes=False,
    )

    guide = generated.guides[0]
    policy = generated.policies[0]
    assert policy.entry == "situational-choice"
    assert BuildPolicy.from_dict(policy.as_dict()) == policy
    assert len(policy.counter_cards) == 1
    choice = next(node for node in policy.nodes if node.node_id == policy.entry)
    assert [guard.field for guard in choice.branches[0].guards] == [
        "enemy.threats",
        "enemy.heroes",
    ]
    tier_item = next(item for item in guide.tiers[1] if item.item_id == 103)
    assert tier_item.tactical_annotation.startswith("If enemy 7's healing")
    assert "over Tier 1 Item 4" in tier_item.tactical_annotation
    assert [category.name for category in guide.categories] == [
        "CORE ITEMS",
        "TIER 1",
        "TIER 2",
        "TIER 3",
        "TIER 4",
    ]
    assert [category.optional for category in guide.categories] == [
        False,
        True,
        True,
        True,
        True,
    ]
    action = next(
        row
        for row in generated.contexts[0]["explainable_actions"]
        if row["node_id"] == "situational-1"
    )
    assert action["conditional_contract"]["comparator_item"] == "Tier 1 Item 4"
