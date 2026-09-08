from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from deadlock_build_sync.match_choices import parse_automatic_branches
from deadlock_build_sync.protobuf import parse_fields
from deadlock_build_sync.purchase_categories import (
    build_purchase_categories,
    split_guidance,
)
from deadlock_build_sync.purchase_guidance import attach_purchase_guidance
from deadlock_build_sync.purchase_purposes import classify_item_purpose
from deadlock_build_sync.snapshot import sha256_json
from tests.match_choice_fixtures import make_branch_document
from tests.purchase_guidance_fixtures import (
    make_guidance_assets,
    make_purchase_guidance,
)
from tests.rendering_fixtures import decode_build_details

if TYPE_CHECKING:
    from deadlock_build_sync.purchase_types import PurchaseGuide


def test_steam_decoding_preserves_core_queue_and_every_optional_pool_item() -> None:
    guide, _ = make_purchase_guidance()
    branch = parse_automatic_branches(make_branch_document(), {7}, (1, 3, 2, 4, 5))[0]
    guide = attach_purchase_guidance(
        replace(guide, automatic_branches=(branch,)), make_guidance_assets()
    )
    assert guide.purchase_guidance is not None
    rows = guide.categories
    assert all(row.optional for row in rows if "CONDITIONAL" in row.name)
    condition_index = next(
        index for index, row in enumerate(rows) if "CONDITIONAL" in row.name
    )
    assert (
        next(row.name for row in rows[condition_index:] if not row.optional) == "CORE 3"
    )
    assert "wealth is behind" in "".join(row.description for row in rows)
    assert all(len(row.description.encode()) <= 240 for row in rows)
    assert all(row.name.startswith("ITEM POOL") for row in rows[-4:])
    queued, optional = _decoded_items(guide)
    assert queued == [1, 3, 2, 4, 5]
    assert optional == {6, 7, 8, 9, 10, 11, 12}
    missing = replace(guide.purchase_guidance, automatic_branches=(branch,))
    with pytest.raises(ValueError, match="canonical purchase plan"):
        build_purchase_categories(replace(guide, purchase_guidance=missing))


@pytest.mark.parametrize(
    "text", ["", "文" * 190, "option " * 170, "x" * 481, "x" * 240 + " more"]
)
def test_guidance_split_preserves_every_character(text: str) -> None:
    parts = split_guidance(text)
    assert "".join(parts) == text
    assert all(0 < len(part.encode()) <= 240 for part in parts)


def _decoded_items(guide: PurchaseGuide) -> tuple[list[int | bytes], set[int | bytes]]:
    encoded = [
        field.value
        for field in decode_build_details(guide)
        if field.number == 1 and isinstance(field.value, bytes)
    ]
    queued, optional = [], set()
    for value in encoded:
        fields = list(parse_fields(value))
        optional_flag = next(field.value for field in fields if field.number == 6)
        for field in fields:
            if field.number != 1 or not isinstance(field.value, bytes):
                continue
            item = next(
                part.value for part in parse_fields(field.value) if part.number == 1
            )
            if optional_flag:
                optional.add(item)
            else:
                queued.append(item)
    return queued, optional


def test_guide_fingerprint_survives_json_with_item_ids_of_different_lengths() -> None:
    guide, _ = make_purchase_guidance()
    assert guide.purchase_guidance is not None
    document = guide.purchase_guidance.as_dict()
    assert sha256_json(document) == sha256_json(json.loads(json.dumps(document)))


def test_choice_purpose_does_not_depend_on_json_object_key_order() -> None:
    description = {
        "z": "Gain bonus souls on assists.",
        "a": "Stay alive while holding the egg to earn souls.",
    }
    assert classify_item_purpose({"description": description}) == classify_item_purpose({
        "description": dict(reversed(list(description.items())))
    })


def test_each_conditional_row_uses_its_own_trigger_and_checkpoint() -> None:
    guide, _ = make_purchase_guidance()
    first = parse_automatic_branches(make_branch_document(), {7}, (1, 3, 2, 4, 5))[0]
    second = replace(
        first, condition="enemy_hero", value=42, after_step=1, comparator_item_id=3
    )
    guide = attach_purchase_guidance(
        replace(guide, automatic_branches=(first, second)), make_guidance_assets()
    )
    descriptions = [
        row.description for row in guide.categories if "CONDITIONAL" in row.name
    ]
    wealth = next(text for text in descriptions if "wealth is behind" in text)
    enemy = next(text for text in descriptions if "enemy hero 42" in text)
    assert "after step 2" in wealth and "enemy hero" not in wealth
    assert "after step 1" in enemy and "wealth" not in enemy
