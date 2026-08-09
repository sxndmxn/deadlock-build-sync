from deadlock_build_sync.ability_order import AbilityPath
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
    return PurchaseGuide(12, "Kelvin", "hero_kelvin", {1: (item,), 2: (), 3: (), 4: ()})


def ability_guide() -> PurchaseGuide:
    guide = sample_guide()
    path = (10, 10, 20, 30, 10, 20, 40, 20, 30, 10, 20, 30, 30, 40, 40, 40)
    return PurchaseGuide(
        guide.hero_id,
        guide.hero_name,
        guide.hero_class_name,
        guide.tiers,
        ability_path=AbilityPath(path, 100, 60, 40, 250),
        summary="Core profile: ability damage and uptime.",
        tier_summaries={1: "Leading options: Test Item."},
    )


def test_build_wrapper_and_metadata_round_trip() -> None:
    build = encode_hero_build(
        sample_guide(),
        build_id=34,
        account_id=146293212,
        persona="XMLJDX",
        timestamp=1234567890,
        patch_title="Test Patch",
        patch_published_at="2026-01-01T00:00:00Z",
    )
    wrapper = wrap_hero_build(build)
    assert extract_hero_build(wrapper) == build
    metadata = hero_build_metadata(wrapper)
    assert metadata.build_id == 34
    assert metadata.hero_id == 12
    assert metadata.author_account_id == 146293212
    assert metadata.name == "XMLJDX | Kelvin | Test Patch"
    assert MANAGED_MARKER in (metadata.description or "")
    assert "Ranks: Emissary I–Eternus V." in (metadata.description or "")
    assert "ruleset: NORMAL" in (metadata.description or "")
    assert metadata.publish_timestamp is None


def test_build_name_truncates_a_long_deadlock_patch_title() -> None:
    build = encode_hero_build(
        sample_guide(),
        build_id=34,
        account_id=146293212,
        persona="XMLJDX",
        timestamp=1234567890,
        patch_title="A Very Long Deadlock Update Title That Would Overflow The Name",
        patch_published_at="2026-01-01T00:00:00Z",
    )
    metadata = hero_build_metadata(build)
    assert metadata.name is not None
    assert len(metadata.name) == 50
    assert metadata.name.startswith("XMLJDX | Kelvin | A Very Long Deadlock")


def test_encodes_native_ability_order_and_descriptions() -> None:
    build = encode_hero_build(
        ability_guide(),
        build_id=34,
        account_id=146293212,
        persona="XMLJDX",
        timestamp=1234567890,
        patch_title="Test Patch",
        patch_published_at="2026-01-01T00:00:00Z",
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
        b"State-conditioned projection | final support 100 | observed outcome rate 60.0%"
    )
    assert second[1] == 10
    assert second[2] == 1
    assert second[3] == (1 << 64) - 1
