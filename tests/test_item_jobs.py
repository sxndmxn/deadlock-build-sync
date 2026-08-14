from deadlock_build_sync.item_jobs import annotate_optional_items, mechanics_job
from deadlock_build_sync.purchase_guide import (
    GuideCategory,
    GuideItem,
    PurchaseGuide,
)


def item(item_id: int = 1) -> GuideItem:
    return GuideItem(item_id, "Option", 1, 20, 0.5, 0.4, 0.2, ())


def test_mechanics_jobs_use_explicit_rules_and_neutral_abstention() -> None:
    assert mechanics_job({"description": "Gain Bullet Resist."}, item()) == (
        "Bullet defense"
    )
    assert mechanics_job({"is_active_item": True}, item()) == "Active use"
    assert mechanics_job({"description": "Plain damage."}, item()) == (
        "Reference option"
    )


def test_optional_annotation_leads_with_job_and_keeps_observation_subordinate() -> None:
    option = GuideItem(
        1,
        "Barrier",
        1,
        20,
        0.5,
        0.4,
        0.2,
        (),
        eligible_player_matches=100,
        adopter_matches=40,
        purchase_adoption=0.4,
        buy_net_worth_q25=5_000,
        buy_net_worth_q75=8_000,
    )
    guide = PurchaseGuide(
        12,
        "Kelvin",
        "hero_kelvin",
        {1: (option,)},
        categories=(GuideCategory("TIER 1", (option,), optional=True),),
    )

    annotated = annotate_optional_items(
        guide,
        [{"id": 1, "description": "Gain Spirit Resist."}],
    )

    text = annotated.categories[0].items[0].annotation
    assert text.startswith("Job: Spirit defense.\nUsually 5k–8k souls")
    assert "Win rate" not in text
    assert len(text.encode("utf-8")) <= 240
