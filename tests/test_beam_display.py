"""Check complete variant recipes and native tier panels."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from deadlock_build_sync.beam_display import (
    generator_metadata,
    variant_statistics,
)
from deadlock_build_sync.guide_groups import build_group_record, group_guides
from deadlock_build_sync.purchase_markdown import render_purchase_markdown
from deadlock_build_sync.service import generate_guides
from deadlock_build_sync.value_validation import require_object_rows
from tests.beam_fixtures import make_generator_path
from tests.service_evidence_fixtures import make_service_build_evidence
from tests.service_fake_api import FakeApi, make_ability_rows, make_duration_statistics
from tests.test_protobuf import presentation

if TYPE_CHECKING:
    from deadlock_build_sync.purchase_types import PurchaseGuide


def make_beam_guide() -> PurchaseGuide:
    api = FakeApi(
        ability_rows=make_ability_rows(), duration_points=make_duration_statistics()
    )
    catalog = make_service_build_evidence(api)
    evidence = catalog.heroes[12]
    metadata = make_generator_path(
        evidence.core_policy.default_item_ids, 12, evidence.path_id
    )
    evidence = replace(evidence, generator=metadata)
    catalog = replace(catalog, generator="beam", heroes={12: evidence})
    generated = generate_guides(
        api, build_evidence=catalog, account_id=0, hero_query="Kelvin", all_heroes=False
    )
    return generated.guides[0]


def test_complete_markdown_keeps_every_variant_pool_and_named_ability() -> None:
    guide = make_beam_guide()
    variant = replace(guide, path_id="variant", core_items=guide.core_items[:-1])
    result = group_guides(
        [guide, variant],
        {(12, guide.path_id): guide.path_id, (12, "variant"): guide.path_id},
    )[0]
    body = render_purchase_markdown(result)
    assert "## TIER 3" in body and "## TIER 4" in body
    assert "## V1" not in body
    assert len(require_object_rows(build_group_record(result)["variants"])) == 2
    details = render_purchase_markdown(result, details=True)
    assert "Choice details" in details and "state_evidence" in details
    assert "Ability 1" in details
    assert "110/200 wins" in details and "Variant samples can overlap" in details
    assert "110/200 wins" in presentation(result).description
    assert [
        item.item_id
        for row in result.categories
        if not row.optional
        for item in row.items
    ] == [item.item_id for item in guide.core_purchase_items]
    assert all(len(row.description.encode()) <= 240 for row in result.categories)


@pytest.mark.parametrize("variant_count", [1, 30])
def test_layout_keeps_all_variant_items_and_default_queue(variant_count: int) -> None:
    guide = make_beam_guide()
    variant_item = replace(guide.core_items[0], item_id=901, name="Variant component")
    late_item = replace(
        guide.core_items[0], item_id=902, tier=4, name="Variant late item"
    )
    variants = tuple(
        replace(
            guide,
            path_id=f"variant-{index:02}",
            core_purchase_items=(*guide.core_purchase_items, variant_item),
            tiers={**guide.tiers, 4: (*guide.tiers[4], late_item)},
        )
        for index in range(variant_count)
    )
    projected = group_guides([replace(guide, variant_guides=variants)], {})[0]
    official = presentation(projected)
    assert projected.core_purchase_items == guide.core_purchase_items
    assert [category.name for category in official.categories] == [
        "CORE",
        "CORE OPTIONAL",
        "TIER 1",
        "TIER 2",
        "TIER 3",
        "TIER 4",
    ]
    shown = [
        item.item_id for category in official.categories for item in category.items
    ]
    expected = {
        item.item_id
        for member in (guide, *variants)
        for item in (
            *member.core_purchase_items,
            *member.optional_core_items,
            *(item for items in member.tiers.values() for item in items),
        )
    }
    assert set(shown) == expected
    assert shown.count(901) == shown.count(902) == 1
    assert 902 in {item.item_id for item in official.categories[-1].items}
    assert f"V{variant_count}:" in official.description


def test_empty_tiers_remain_present() -> None:
    guide = make_beam_guide()
    projected = group_guides(
        [replace(guide, tiers=dict.fromkeys(range(1, 5), ()))], {}
    )[0]
    assert [category.name for category in projected.categories[-4:]] == [
        "TIER 1",
        "TIER 2",
        "TIER 3",
        "TIER 4",
    ]
    assert all(
        category.optional
        and not category.items
        and category.description == "No supported options."
        for category in presentation(projected).categories[-4:]
    )


@pytest.mark.parametrize("missing_tier", [3, 4])
def test_presentation_rejects_missing_tier_panel(missing_tier: int) -> None:
    guide = group_guides([make_beam_guide()], {})[0]
    categories = tuple(
        row for row in guide.categories if row.name != f"TIER {missing_tier}"
    )
    with pytest.raises(ValueError, match="all four tier panels"):
        presentation(replace(guide, categories=categories))


def test_presentation_rejects_missing_tier_item_and_changed_queue() -> None:
    guide = group_guides([make_beam_guide()], {})[0]
    categories = (*guide.categories[:-1], replace(guide.categories[-1], items=()))
    with pytest.raises(ValueError, match="complete variant pools"):
        presentation(replace(guide, categories=categories))
    core = replace(
        guide.categories[0], items=tuple(reversed(guide.categories[0].items))
    )
    with pytest.raises(ValueError, match="canonical component path"):
        presentation(replace(guide, categories=(core, *guide.categories[1:])))


def test_presentation_rejects_required_optional_panel() -> None:
    guide = group_guides([make_beam_guide()], {})[0]
    categories = (*guide.categories[:-1], replace(guide.categories[-1], optional=False))
    with pytest.raises(ValueError, match="must remain optional"):
        presentation(replace(guide, categories=categories))


def test_missing_statistics_and_fallback_remain_explicit() -> None:
    guide = make_beam_guide()
    metadata = {
        **generator_metadata(guide),
        "effective": "current",
        "fallback_reason": "No supported beam route",
    }
    fallback = replace(guide, evidence_summary={"generator": metadata})
    assert "No supported beam route" in render_purchase_markdown(fallback, details=True)
    assert variant_statistics(replace(guide, evidence_summary={})) == []
