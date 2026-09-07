from dataclasses import replace
from datetime import UTC, datetime

from deadlock_build_sync.build_evidence import (
    BuildEvidenceCatalog,
    CoreAlternativeEvidence,
    CorePolicyEvidence,
    HeroBuildEvidence,
    ItemEvidence,
    SequencePolicy,
    SequenceTransition,
    SituationalBranch,
    SituationalPolicy,
    TierPolicyEvidence,
)
from deadlock_build_sync.purchase_guidance_types import PurchaseTiming
from deadlock_build_sync.snapshot import (
    sha256_json,
)
from deadlock_build_sync.value_validation import (
    integer,
)
from tests.service_fake_api import FakeApi


def _item_evidence(asset: dict[str, object], eligible: int) -> ItemEvidence:
    item_id = integer(asset["id"])
    adopter_matches = 90 - item_id % 100
    test_adopter_matches = 20 - item_id % 100
    return ItemEvidence(
        item_id=item_id,
        item=str(asset["name"]),
        tier=integer(asset["item_tier"]),
        cost=integer(asset["cost"]),
        slot=str(asset["item_slot_type"]),
        active=False,
        adopter_matches=adopter_matches,
        eligible_player_matches=eligible,
        purchase_events=100,
        wins=50,
        adoption=adopter_matches / eligible,
        observed_outcome_rate=50 / adopter_matches,
        median_buy_time_s=float(item_id),
        median_valid_buy_net_worth=float(item_id * 10),
        buy_net_worth_q25=float(item_id * 9),
        buy_net_worth_q75=float(item_id * 11),
        valid_buy_net_worth_share=0.9,
        selection_adopter_matches=70,
        selection_eligible_player_matches=80,
        training_adopter_matches=35,
        training_eligible_player_matches=40,
        validation_adopter_matches=35,
        validation_eligible_player_matches=40,
        test_adopter_matches=test_adopter_matches,
        test_eligible_player_matches=20,
        selection_adoption=70 / 80,
        training_adoption=35 / 40,
        validation_adoption=35 / 40,
        test_adoption=test_adopter_matches / 20,
        selection_median_buy_time_s=float(item_id),
        selection_median_valid_buy_net_worth=float(item_id * 10),
        selection_buy_net_worth_q25=float(item_id * 9),
        selection_buy_net_worth_q75=float(item_id * 11),
        selection_valid_buy_net_worth_share=1.0,
        selection_valid_buy_net_worth_observations=70,
        training_valid_buy_net_worth_observations=35,
        validation_valid_buy_net_worth_observations=35,
        training_buy_net_worth_q25=float(item_id * 9),
        training_buy_net_worth_q75=float(item_id * 11),
        validation_buy_net_worth_q25=float(item_id * 9),
        validation_buy_net_worth_q75=float(item_id * 11),
    )


def build_evidence(
    api: FakeApi,
    *,
    with_situational_branch: bool = False,
    with_component_path: bool = False,
    with_core_alternative: bool = False,
) -> BuildEvidenceCatalog:
    eligible = 100
    item_rows = tuple(
        _item_evidence(asset, eligible)
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
                    enemy_scope="same_lane",
                    phase=1,
                    tier=1,
                    mechanic_ref="item/103/healing",
                    enemy_mechanics_refs=("asset:ability:7:description",),
                    comparator="same-opportunity item 100 or save",
                    comparator_item_id=100,
                    comparison_support=30,
                    same_opportunity=True,
                    support=40,
                    effective_support=30.0,
                    overlap=0.8,
                    stable=True,
                    comparative_interval=(0.01, 0.06),
                    trigger="Enemy hero 7 presents material healing.",
                    replacement="Choose item 103 instead of item 100.",
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
        selection_eligible_player_matches=80,
        fold_eligible_player_matches={"train": 40, "validation": 40, "test": 20},
        median_final_net_worth=20_000,
        items=item_rows,
        core_policy=CorePolicyEvidence(
            (100, 101, 200, 201),
            (100, 101, 200, 201, 300, 301, 400, 401),
            60,
            {"train": 20, "validation": 20, "test": 20},
            40,
            (
                CoreAlternativeEvidence(
                    item_id=103,
                    comparator_item_id=101,
                    stage=2,
                    support=40,
                    comparison_support=40,
                    effective_support=30.0,
                    overlap=0.8,
                    stable=True,
                    dr_estimate=0.03,
                    comparative_interval=(0.01, 0.05),
                    vs="Heavy enemy healing",
                    why="Healing Reduction",
                    swap="Replaces Tier 1 Item 1",
                    when="Before the next fight with heavy enemy healing",
                    skip="Keep default when weapon pressure matters more",
                    mechanics_refs=("asset:item:103:description",),
                    comparator_mechanics_refs=("asset:item:101:description",),
                    fold_estimates={
                        "train": 0.03,
                        "validation": 0.04,
                        "test": -0.01,
                    },
                ),
            )
            if with_core_alternative
            else (),
            (),
            {"method": "cross-fitted-dr"},
        ),
        tier_policy=TierPolicyEvidence({
            tier: tuple(
                item.item_id
                for item in item_rows
                if item.tier == tier
                and item.item_id
                not in {
                    100,
                    101,
                    200,
                    201,
                    300,
                    301,
                    400,
                    401,
                    *((with_component_path and [102]) or []),
                    *((with_core_alternative and [103]) or []),
                }
            )
            for tier in range(1, 5)
        }),
        sequence_policy=(
            SequencePolicy(
                (100, 101, 102, 200, 201, 300, 301, 400, 401),
                (SequenceTransition("popularity", 0, 0, 0, 100, 40, 100),),
                20,
                "deterministic_backoff",
                {"chronological_fold": "test"},
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


def grouped_build_evidence(api: FakeApi) -> BuildEvidenceCatalog:
    evidence = build_evidence(api)
    hero = evidence.heroes[12]
    timing = tuple(
        PurchaseTiming(item, 35, (25, *(0 for _ in hero.core_policy.default_item_ids)))
        for values in hero.tier_policy.item_ids_by_tier.values()
        for item in values
    )
    hero = replace(hero, purchase_timing=timing)
    variant = replace(
        hero,
        path_id="alternative",
        guide_group_id=hero.path_id,
        core_policy=replace(
            hero.core_policy,
            default_item_ids=(*hero.core_policy.default_item_ids[:-1], 402),
        ),
        tier_policy=replace(
            hero.tier_policy,
            item_ids_by_tier={
                tier: tuple(401 if item == 402 else item for item in items)
                for tier, items in hero.tier_policy.item_ids_by_tier.items()
            },
        ),
        purchase_timing=tuple(
            replace(point, item_id=401) if point.item_id == 402 else point
            for point in timing
        ),
    )
    return replace(evidence, heroes={12: hero}, hero_builds={12: (hero, variant)})
