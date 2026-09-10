"""Check complete variant recipes and bounded native display categories."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from deadlock_build_sync.beam_display import (
    category_extent,
    compact_beam_guide,
    generator_metadata,
    variant_category,
    variant_statistics,
)
from deadlock_build_sync.guide_groups import build_group_record, group_guides
from deadlock_build_sync.purchase_markdown import render_purchase_markdown
from deadlock_build_sync.purchase_types import GuideCategory
from deadlock_build_sync.service import generate_guides
from deadlock_build_sync.value_validation import (
    require_object_dict,
    require_object_rows,
)
from tests.beam_fixtures import make_generator_path
from tests.service_evidence_fixtures import make_service_build_evidence
from tests.service_fake_api import FakeApi, make_ability_rows, make_duration_statistics

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
    assert "Shared final items" in body and "Variant 1" in body
    assert "Tier 4 options" in body and "Ability 1" in body
    assert "110/200 wins" in body and "Variant samples can overlap" in body
    assert "Compact display: {" not in body
    assert len(require_object_rows(build_group_record(result)["variants"])) == 2
    details = render_purchase_markdown(result, details=True)
    assert "Choice details" in details and "state_evidence" in details
    assert [
        item.item_id
        for row in result.categories
        if not row.optional
        for item in row.items
    ] == [item.item_id for item in guide.core_purchase_items]
    assert all(len(row.description.encode()) <= 240 for row in result.categories)


def test_compact_layout_reports_omissions_and_preserves_default_queue() -> None:
    guide = make_beam_guide()
    variants = tuple(replace(guide, path_id=f"variant-{index}") for index in range(30))
    projected = compact_beam_guide(replace(guide, variant_guides=variants))
    display = require_object_dict(projected.evidence_summary["display"])
    assert display["omitted_variants"]
    assert display["live_client_verified"] is False
    assert projected.core_purchase_items == guide.core_purchase_items
    assert category_extent(projected.categories) == display["extent"]
    assert (
        variant_category(
            replace(guide, core_purchase_items=guide.core_purchase_items * 3),
            frozenset(),
            1,
        )
        is None
    )
    giant = compact_beam_guide(
        replace(guide, core_purchase_items=guide.core_purchase_items * 12)
    )
    assert require_object_dict(giant.evidence_summary["display"])["overflow"] is True
    assert category_extent(()) == (0, 0)


def test_short_variant_recipe_reconstructs_common_core_without_claiming_order() -> None:
    guide = make_beam_guide()
    route = tuple(
        replace(item, name=f"Item{index}")
        for index, item in enumerate(guide.core_purchase_items[:4])
    )
    guide = replace(guide, core_items=route, core_purchase_items=route)
    shared = frozenset(item.item_id for item in route[:3])
    category = variant_category(guide, shared, 2)
    assert category is not None and category.optional
    assert shared | {item.item_id for item in category.items} == {
        item.item_id for item in route
    }
    assert "Order: Item0 > Item1 > Item2 > Item3" in category.description
    assert category.name == "V2 Even"
    assert category_extent((GuideCategory("small", (), compact=True),)) == (256, 48)


def test_missing_statistics_and_fallback_remain_explicit() -> None:
    guide = make_beam_guide()
    metadata = {
        **generator_metadata(guide),
        "effective": "current",
        "fallback_reason": "No supported beam route",
    }
    fallback = replace(guide, evidence_summary={"generator": metadata})
    assert (
        "Current-guide fallback: No supported beam route"
        in render_purchase_markdown(fallback)
    )
    assert variant_statistics(replace(guide, evidence_summary={})) == []
