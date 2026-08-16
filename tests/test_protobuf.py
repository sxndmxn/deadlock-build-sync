import struct
from dataclasses import replace

from deadlock_build_sync.ability_order import AbilityPath
from deadlock_build_sync.presentation import BuildPresentation, build_presentation
from deadlock_build_sync.protobuf import (
    MANAGED_MARKER,
    encode_hero_build,
    extract_hero_build,
    hero_build_metadata,
    parse_fields,
    wrap_hero_build,
)
from deadlock_build_sync.purchase_guide import GuideItem, PurchaseGuide, PurchaseWindow


def sample_guide() -> PurchaseGuide:
    window = PurchaseWindow(5000, 10000, 100, 60, 0.6, 0.5)
    item = GuideItem(123, "Test Item", 1, 200, 0.55, 0.48, 1.0, (window,))
    return PurchaseGuide(
        12,
        "Kelvin",
        "hero_kelvin",
        {1: (item,), 2: (), 3: (), 4: ()},
        build_tag_ids=(1, 2, 3),
        build_archetype="Spirit Damage",
        as_of_timestamp=1_767_225_600,
        client_version=123,
        match_mode="ranked",
    )


def presentation(
    guide: PurchaseGuide, patch_title: str = "Test Patch"
) -> BuildPresentation:
    return build_presentation(
        guide,
        patch_title=patch_title,
        patch_published_at="2026-01-01T00:00:00Z",
    )


def ability_guide() -> PurchaseGuide:
    guide = sample_guide()
    path = (10, 10, 20, 30, 10, 20, 40, 20, 30, 10, 20, 30, 30, 40, 40, 40)
    return replace(
        guide,
        ability_path=AbilityPath(path, 100, 60, 40, 250),
        summary="Core profile: ability damage and uptime.",
        tier_summaries={1: "Leading options: Test Item."},
    )


def eleven_item_guide() -> PurchaseGuide:
    window = PurchaseWindow(5000, 10000, 100, 60, 0.6, 0.5)

    def item(item_id: int, tier: int) -> GuideItem:
        return GuideItem(
            item_id,
            f"Item {item_id}",
            tier,
            200,
            0.55,
            0.48,
            1.0,
            (window,),
        )

    return PurchaseGuide(
        35,
        "Viscous",
        "hero_viscous",
        {
            tier: tuple(item(tier * 100 + index, tier) for index in range(10))
            for tier in range(1, 5)
        },
        core_items=tuple(item(500 + index, 4) for index in range(11)),
        build_tag_ids=(1, 2, 3),
        build_archetype="Utility / Vitality",
        as_of_timestamp=1_767_225_600,
        client_version=123,
        match_mode="ranked",
    )


def test_build_wrapper_and_metadata_round_trip() -> None:
    build = encode_hero_build(
        presentation(sample_guide()),
        build_id=34,
        account_id=146293212,
        timestamp=1234567890,
    )
    wrapper = wrap_hero_build(build)
    assert extract_hero_build(wrapper) == build
    metadata = hero_build_metadata(wrapper)
    assert metadata.build_id == 34
    assert metadata.hero_id == 12
    assert metadata.author_account_id == 146293212
    assert metadata.name == "Spirit Damage | Ranked | 2026-01-01"
    assert metadata.tag_ids == (1, 2, 3)
    assert MANAGED_MARKER in (metadata.description or "")
    assert "Emissary I–Eternus V" in (metadata.description or "")
    assert "Ranked" in (metadata.description or "")
    assert metadata.publish_timestamp is None


def test_build_name_truncates_a_long_deadlock_patch_title() -> None:
    build = encode_hero_build(
        presentation(
            sample_guide(),
            "A Very Long Deadlock Update Title That Would Overflow The Name",
        ),
        build_id=34,
        account_id=146293212,
        timestamp=1234567890,
    )
    metadata = hero_build_metadata(build)
    assert metadata.name is not None
    assert metadata.name == "Spirit Damage | Ranked | 2026-01-01"


def test_encodes_native_ability_order_and_descriptions() -> None:
    build = encode_hero_build(
        presentation(ability_guide()),
        build_id=34,
        account_id=146293212,
        timestamp=1234567890,
    )
    metadata = hero_build_metadata(build)
    assert "Core profile: ability damage and uptime." in (metadata.description or "")

    details = next(
        field.value
        for field in parse_fields(build)
        if field.number == 10 and isinstance(field.value, bytes)
    )
    details_fields = list(parse_fields(details))
    first_category = next(
        field.value
        for field in details_fields
        if field.number == 1 and isinstance(field.value, bytes)
    )
    category_description = next(
        field.value.decode()
        for field in parse_fields(first_category)
        if field.number == 3 and isinstance(field.value, bytes)
    )
    assert category_description == "Leading options: Test Item."

    ability_order = next(
        field.value
        for field in details_fields
        if field.number == 2 and isinstance(field.value, bytes)
    )
    changes = [
        field.value
        for field in parse_fields(ability_order)
        if field.number == 1 and isinstance(field.value, bytes)
    ]
    assert len(changes) == 16

    first = {field.number: field.value for field in parse_fields(changes[0])}
    second = {field.number: field.value for field in parse_fields(changes[1])}
    assert first[1] == 10
    assert first[2] == 2
    assert first[3] == (1 << 64) - 1
    assert first[4] == (
        b"State-composed observed default \xe2\x80\xa2 tail support n=100 "
        b"\xe2\x80\xa2 observational."
    )
    assert second[1] == 10
    assert second[2] == 1
    assert second[3] == (1 << 64) - 1


def test_encodes_the_viscous_layout_with_eleven_core_cards() -> None:
    build = encode_hero_build(
        presentation(eleven_item_guide()),
        build_id=34,
        account_id=146293212,
        timestamp=1234567890,
    )
    details = next(
        field.value
        for field in parse_fields(build)
        if field.number == 10 and isinstance(field.value, bytes)
    )
    encoded_categories = [
        field.value
        for field in parse_fields(details)
        if field.number == 1 and isinstance(field.value, bytes)
    ]
    expected = {
        "CORE ITEMS": (11, 567.0, 307.5),
        "TIER 1": (10, 465.75, 318.75),
        "TIER 2": (10, 562.5, 315.75),
        "TIER 3": (10, 465.75, 319.5),
        "TIER 4": (10, 1039.5, 152.25),
    }

    actual: dict[str, tuple[int, float, float]] = {}
    for category in encoded_categories:
        fields = list(parse_fields(category))
        name = next(
            field.value.decode()
            for field in fields
            if field.number == 2 and isinstance(field.value, bytes)
        )
        width = struct.unpack(
            "<f",
            next(
                field.value
                for field in fields
                if field.number == 4 and isinstance(field.value, bytes)
            ),
        )[0]
        height = struct.unpack(
            "<f",
            next(
                field.value
                for field in fields
                if field.number == 5 and isinstance(field.value, bytes)
            ),
        )[0]
        actual[name] = (
            sum(field.number == 1 for field in fields),
            width,
            height,
        )

    assert actual == expected
