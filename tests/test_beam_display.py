"""Check complete variant recipes and native tier panels."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from deadlock_build_sync.beam_display import (
    generator_metadata,
    variant_state_labels,
    variant_statistics,
)
from deadlock_build_sync.guide_groups import build_group_record, group_guides
from deadlock_build_sync.purchase_markdown import render_purchase_markdown
from deadlock_build_sync.service import generate_guides
from deadlock_build_sync.value_validation import (
    require_object_dict,
    require_object_rows,
)
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
    assert "## CORE ITEMS" in body and "## ALTERNATIVE CORE" in body
    assert "## VARIANT 1" in body
    assert "## CORE OPTIONAL" not in body
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
        "CORE ITEMS",
        "ALTERNATIVE CORE",
        *(f"VARIANT {index}" for index in range(1, variant_count + 1)),
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
    assert 901 in {
        item.item_id
        for category in official.categories
        if category.name == "TIER 1"
        for item in category.items
    }
    assert 902 in {item.item_id for item in official.categories[-1].items}
    assert f"V{variant_count} (Even):" in official.description
    assert "Queue follows CORE ITEMS only." in official.description


def test_variant_panels_preserve_combinations_and_specific_imbue_targets() -> None:
    guide = make_beam_guide()
    shared = guide.core_items[:-2]
    first, second = guide.core_items[-2:]
    extra = guide.tiers[4][0]
    variants = (
        replace(
            guide,
            path_id="v1",
            core_items=(*shared, first, replace(extra, imbue_target_ability_id=10)),
        ),
        replace(
            guide,
            path_id="v2",
            core_items=(*shared, replace(extra, imbue_target_ability_id=20), second),
        ),
    )
    projected = group_guides([replace(guide, variant_guides=variants)], {})[0]
    categories = {
        category.name: category for category in presentation(projected).categories
    }
    assert [item.item_id for item in categories["ALTERNATIVE CORE"].items] == [
        item.item_id for item in shared
    ]
    assert [item.item_id for item in categories["VARIANT 1"].items] == [
        first.item_id,
        extra.item_id,
    ]
    assert [item.item_id for item in categories["VARIANT 2"].items] == [
        extra.item_id,
        second.item_id,
    ]
    assert categories["VARIANT 1"].items[1].imbue_target_ability_id == 10
    assert categories["VARIANT 2"].items[0].imbue_target_ability_id == 20
    assert categories["ALTERNATIVE CORE"].description == "Combine with one VARIANT."
    assert categories["VARIANT 1"].description == (
        "ALTERNATIVE CORE +\nEven: 55.0% | 110/200 wins"
    )
    assert categories["VARIANT 2"].optional
    # The same item can be a supported tier option and part of a complete variant.
    assert extra.item_id in {item.item_id for item in categories["TIER 4"].items}
    changed = tuple(
        replace(category, items=category.items[:-1])
        if category.name == "VARIANT 2"
        else category
        for category in projected.categories
    )
    with pytest.raises(ValueError, match="complete core combinations"):
        presentation(replace(projected, categories=changed))


def test_variant_without_shared_items_shows_its_complete_final_core() -> None:
    guide = make_beam_guide()
    variant = replace(guide, path_id="other", core_items=guide.tiers[1][:2])
    projected = group_guides([replace(guide, variant_guides=(variant,))], {})[0]
    official = presentation(projected)
    assert [category.name for category in official.categories] == [
        "CORE ITEMS",
        "VARIANT 1",
        "TIER 1",
        "TIER 2",
        "TIER 3",
        "TIER 4",
    ]
    assert [item.item_id for item in official.categories[1].items] == [
        item.item_id for item in variant.core_items
    ]
    assert official.categories[1].description == (
        "Full core.\nEven: 55.0% | 110/200 wins"
    )
    assert (
        "Each VARIANT panel contains its complete final core." in official.description
    )


def test_missing_variant_panel_fails_even_when_its_items_appear_elsewhere() -> None:
    guide = make_beam_guide()
    projected = group_guides(
        [replace(guide, variant_guides=(replace(guide, path_id="v1"),))], {}
    )[0]
    categories = tuple(
        category for category in projected.categories if category.name != "VARIANT 1"
    )
    with pytest.raises(ValueError, match="each variant"):
        presentation(replace(projected, categories=categories))


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


def test_conditional_core_items_remain_separate_from_variant_combinations() -> None:
    guide = make_beam_guide()
    conditional = guide.tiers[2][0]
    variant = replace(guide, path_id="v1", optional_core_items=(conditional,))
    projected = group_guides([replace(guide, variant_guides=(variant,))], {})[0]
    categories = {
        category.name: category for category in presentation(projected).categories
    }
    panel = categories["CORE CONDITIONAL"]
    assert panel.optional and [item.item_id for item in panel.items] == [
        conditional.item_id
    ]
    assert "Conditional V1" in panel.items[0].annotation
    assert conditional.item_id not in {
        item.item_id for item in categories["VARIANT 1"].items
    }


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


@pytest.mark.parametrize(
    ("states", "labels"),
    [
        ([0], "Behind"),
        ([1], "Even"),
        ([2], "Ahead"),
        ([2, 0, 1], "Behind, Even, Ahead"),
    ],
)
def test_variant_notes_use_its_own_wealth_states(
    states: list[int], labels: str
) -> None:
    guide = make_beam_guide()
    metadata = generator_metadata(guide)
    evidence = require_object_dict(metadata["state_evidence"])
    metadata = {
        **metadata,
        "states": states,
        "scores": {str(state): 0.1 for state in states},
        "state_evidence": {str(state): deepcopy(evidence["1"]) for state in states},
    }
    variant = replace(
        guide,
        path_id="variant",
        core_items=(*guide.core_items[:-1], guide.tiers[4][0]),
        evidence_summary={**guide.evidence_summary, "generator": metadata},
    )
    official = presentation(
        group_guides([replace(guide, variant_guides=(variant,))], {})[0]
    )
    assert f"V1 ({labels}):" in official.description
    panel = next(row for row in official.categories if row.name == "VARIANT 1")
    assert panel.description.startswith("ALTERNATIVE CORE +\n")
    for label in ("Behind", "Even", "Ahead"):
        assert (f"{label}: 55.0% | 110/200 wins" in panel.description) == (
            label in labels
        )
    assert [
        item.item_id
        for category in official.categories
        if not category.optional
        for item in category.items
    ] == [item.item_id for item in guide.core_purchase_items]


@pytest.mark.parametrize("missing", ["generator", "states", "validation"])
def test_missing_state_evidence_does_not_assign_a_variant_state(missing: str) -> None:
    guide = make_beam_guide()
    metadata = deepcopy(generator_metadata(guide))
    if missing == "states":
        metadata["states"] = []
    elif missing == "validation":
        evidence = require_object_dict(metadata["state_evidence"])
        require_object_dict(evidence["1"])["validation"] = {"owners": 0, "wins": 0}
    variant = replace(
        guide,
        path_id="variant",
        evidence_summary={"generator": metadata} if missing != "generator" else {},
    )
    official = presentation(
        group_guides([replace(guide, variant_guides=(variant,))], {})[0]
    )
    panel = next(row for row in official.categories if row.name == "VARIANT 1")
    assert "State evidence unavailable." in panel.description
    assert "V1 (State unknown):" in official.description
    assert variant_state_labels(variant) == "State unknown"
