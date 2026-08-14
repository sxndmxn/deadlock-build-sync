from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .presentation import MANAGED_MARKER, BuildPresentation

if TYPE_CHECKING:
    from collections.abc import Iterator

    from .purchase_guide import GuideCategory, GuideItem, PurchaseGuide
CATEGORY_LABELS = {1: "I", 2: "II", 3: "III", 4: "IV"}
DEFAULT_CATEGORY_SIZE = (760.0, 164.0)
STANDARD_CATEGORY_SIZES = {
    # Captured from a user-tuned Viscous build at 2560x1440. Source 2 flows
    # categories in encoded order, so these dimensions produce a two-column
    # CORE/TIER 1 row, a two-column TIER 2/TIER 3 row, and a full-width TIER 4.
    # The CORE block has room for eleven item cards across two lines.
    "CORE ITEMS": (567.0, 307.5),
    "TIER 1": (465.75, 318.75),
    "TIER 2": (562.5, 315.75),
    "TIER 3": (465.75, 319.5),
    "TIER 4": (1039.5, 152.25),
}


@dataclass(frozen=True)
class ProtoField:
    number: int
    wire_type: int
    value: int | bytes


@dataclass(frozen=True)
class HeroBuildMetadata:
    build_id: int | None
    hero_id: int | None
    author_account_id: int | None
    name: str | None
    description: str | None
    version: int | None
    publish_timestamp: int | None
    tag_ids: tuple[int, ...]


def encode_varint(value: int) -> bytes:
    if value < 0:
        value &= (1 << 64) - 1
    output = bytearray()
    while value >= 0x80:
        output.append((value & 0x7F) | 0x80)
        value >>= 7
    output.append(value)
    return bytes(output)


def _key(field: int, wire_type: int) -> bytes:
    return encode_varint((field << 3) | wire_type)


def varint_field(field: int, value: int | None) -> bytes:
    if value is None:
        return b""
    return _key(field, 0) + encode_varint(value)


def bool_field(field: int, *, value: bool | None) -> bytes:
    if value is None:
        return b""
    return varint_field(field, int(value))


def float_field(field: int, value: float | None) -> bytes:
    if value is None:
        return b""
    return _key(field, 5) + struct.pack("<f", value)


def bytes_field(field: int, value: bytes) -> bytes:
    return _key(field, 2) + encode_varint(len(value)) + value


def string_field(field: int, value: str | None) -> bytes:
    if value is None:
        return b""
    return bytes_field(field, value.encode("utf-8"))


def message_field(field: int, value: bytes) -> bytes:
    if not value:
        return b""
    return bytes_field(field, value)


def read_varint(buffer: bytes, index: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while True:
        if index >= len(buffer):
            raise ValueError("truncated protobuf varint")
        byte = buffer[index]
        index += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, index
        shift += 7
        if shift > 70:
            raise ValueError("protobuf varint is too long")


def parse_fields(buffer: bytes) -> Iterator[ProtoField]:
    index = 0
    while index < len(buffer):
        key, index = read_varint(buffer, index)
        number = key >> 3
        wire_type = key & 7
        if wire_type == 0:
            value, index = read_varint(buffer, index)
        elif wire_type == 1:
            end = index + 8
            value = buffer[index:end]
            index = end
        elif wire_type == 2:
            length, index = read_varint(buffer, index)
            end = index + length
            value = buffer[index:end]
            index = end
        elif wire_type == 5:
            end = index + 4
            value = buffer[index:end]
            index = end
        else:
            raise ValueError(f"unsupported protobuf wire type {wire_type}")
        if index > len(buffer):
            raise ValueError("truncated protobuf field")
        yield ProtoField(number, wire_type, value)


def extract_hero_build(result_blob: bytes) -> bytes:
    for field in parse_fields(result_blob):
        if (
            field.number != 1
            or field.wire_type != 2
            or not isinstance(field.value, bytes)
        ):
            continue
        nested_numbers = {nested.number for nested in parse_fields(field.value)}
        if 2 in nested_numbers and 5 in nested_numbers:
            return field.value
    return result_blob


def hero_build_metadata(result_blob: bytes) -> HeroBuildMetadata:
    build = extract_hero_build(result_blob)
    values: dict[int, int | str] = {}
    tag_ids: list[int] = []
    for field in parse_fields(build):
        if field.wire_type == 0 and isinstance(field.value, int):
            values[field.number] = field.value
            if field.number == 11:
                tag_ids.append(field.value)
        elif (
            field.wire_type == 2
            and field.number in {5, 6}
            and isinstance(field.value, bytes)
        ):
            values[field.number] = field.value.decode("utf-8", errors="replace")
    build_id = values.get(1)
    hero_id = values.get(2)
    author_account_id = values.get(3)
    name = values.get(5)
    description = values.get(6)
    version = values.get(8)
    publish_timestamp = values.get(13)
    return HeroBuildMetadata(
        build_id=build_id if isinstance(build_id, int) else None,
        hero_id=hero_id if isinstance(hero_id, int) else None,
        author_account_id=(
            author_account_id if isinstance(author_account_id, int) else None
        ),
        name=name if isinstance(name, str) else None,
        description=description if isinstance(description, str) else None,
        version=version if isinstance(version, int) else None,
        publish_timestamp=(
            publish_timestamp if isinstance(publish_timestamp, int) else None
        ),
        tag_ids=tuple(tag_ids),
    )


def _encode_mod(item: GuideItem) -> bytes:
    return (
        varint_field(1, item.item_id)
        + string_field(2, item.annotation)
        + varint_field(3, item.required_flex_slots)
        + varint_field(4, item.sell_priority)
        + varint_field(5, item.imbue_target_ability_id)
    )


def _encode_category(
    category: GuideCategory,
) -> bytes:
    width, height = STANDARD_CATEGORY_SIZES.get(category.name, DEFAULT_CATEGORY_SIZE)
    output = bytearray()
    for item in category.items:
        output += message_field(1, _encode_mod(item))
    output += string_field(2, category.name)
    output += string_field(3, category.description)
    output += float_field(4, width)
    output += float_field(5, height)
    output += bool_field(6, value=category.optional)
    return bytes(output)


def _encode_currency_change(
    ability_id: int,
    *,
    currency_type: int,
    delta: int,
    annotation: str | None = None,
) -> bytes:
    return (
        varint_field(1, ability_id)
        + varint_field(2, currency_type)
        + varint_field(3, delta)
        + string_field(4, annotation)
    )


def _encode_ability_order(presentation: BuildPresentation) -> bytes:
    if presentation.ability_path is None:
        return b""
    output = bytearray()
    purchases: dict[int, int] = {}
    upgrade_costs = (-1, -2, -5)
    for index, ability_id in enumerate(presentation.ability_path.ability_ids):
        prior_purchases = purchases.get(ability_id, 0)
        if prior_purchases == 0:
            currency_type = 2
            delta = -1
        elif prior_purchases <= len(upgrade_costs):
            currency_type = 1
            delta = upgrade_costs[prior_purchases - 1]
        else:
            raise ValueError(f"ability {ability_id} appears too often in ability path")
        annotation = presentation.ability_path.annotation if index == 0 else None
        output += message_field(
            1,
            _encode_currency_change(
                ability_id,
                currency_type=currency_type,
                delta=delta,
                annotation=annotation,
            ),
        )
        purchases[ability_id] = prior_purchases + 1
    return bytes(output)


def encode_hero_build(
    presentation: BuildPresentation,
    *,
    build_id: int,
    account_id: int,
    timestamp: int,
) -> bytes:
    details = bytearray()
    for category in presentation.categories:
        details += message_field(1, _encode_category(category))
    details += message_field(2, _encode_ability_order(presentation))

    output = bytearray()
    output += varint_field(1, build_id)
    output += varint_field(2, presentation.hero_id)
    output += varint_field(3, account_id)
    output += varint_field(4, timestamp)
    output += string_field(5, presentation.name)
    output += string_field(6, presentation.description)
    output += varint_field(7, 0)
    output += varint_field(8, 0)
    output += varint_field(9, 0)
    output += message_field(10, bytes(details))
    for tag_id in presentation.tag_ids:
        output += varint_field(11, tag_id)
    output += bool_field(12, value=False)
    return bytes(output)


def wrap_hero_build(hero_build: bytes) -> bytes:
    return (
        bytes_field(1, hero_build)
        + bytes_field(2, b"")
        + varint_field(3, 0)
        + varint_field(8, 0)
    )


def is_managed_build(
    metadata: HeroBuildMetadata, *, hero_id: int, account_id: int
) -> bool:
    return (
        metadata.hero_id == hero_id
        and metadata.author_account_id == account_id
        and metadata.description is not None
        and MANAGED_MARKER in metadata.description
    )


def describe_guide(
    guide: PurchaseGuide,
    *,
    presentation: BuildPresentation | None = None,
) -> dict[str, Any]:
    ability_path = guide.ability_path
    return {
        "hero_id": guide.hero_id,
        "hero_name": guide.hero_name,
        "item_count": guide.item_count,
        "snapshot_id": guide.snapshot_id,
        "policy_id": guide.policy_id,
        "client_version": guide.client_version,
        "match_mode": guide.match_mode,
        "rank_identity": guide.rank_identity,
        "summary": guide.summary,
        "presentation": (
            {
                "name": presentation.name,
                "tag_ids": list(presentation.tag_ids),
                "description": presentation.description,
            }
            if presentation is not None
            else None
        ),
        "build_tags": {
            "archetype": guide.build_archetype,
            "ids": list(guide.build_tag_ids),
            "classes": list(guide.build_tag_classes),
            "labels": list(guide.build_tag_labels),
            "catalog_sha256": guide.build_tag_catalog_sha256,
        },
        "core": {
            "item_count": len(guide.core_items),
            "joint_player_matches": guide.core_joint_matches,
            "joint_share": guide.core_joint_share,
            "median_final_net_worth": guide.median_final_net_worth,
            "target_cost": guide.core_target_cost,
        },
        "ability_path": (
            {
                "abilities": list(ability_path.ability_ids),
                "final_branch_support_share": (ability_path.final_branch_support_share),
                "observed_final_branch_outcome_rate": (
                    ability_path.observed_final_branch_outcome_rate
                ),
                "minimum_decision_support": ability_path.minimum_decision_support,
                "matches": ability_path.matches,
                "wins": ability_path.wins,
                "losses": ability_path.losses,
                "cohort_matches": ability_path.cohort_matches,
                "annotation": ability_path.annotation,
            }
            if ability_path is not None
            else None
        ),
        "categories": [
            {
                "name": category.name,
                "description": category.description,
                "optional": category.optional,
                "items": [
                    {
                        "item_id": item.item_id,
                        "name": item.name,
                        "annotation": item.annotation,
                        "purchase_event_observations": item.purchase_event_observations,
                        "purchase_adoption": item.purchase_adoption,
                        "adopter_matches": item.adopter_matches,
                        "eligible_player_matches": item.eligible_player_matches,
                        "median_first_ownership_time_s": item.median_buy_time_s,
                        "median_valid_first_ownership_net_worth": item.median_valid_buy_net_worth,
                        "required_flex_slots": item.required_flex_slots,
                        "sell_priority": item.sell_priority,
                        "imbue_target_ability_id": item.imbue_target_ability_id,
                    }
                    for item in category.items
                ],
            }
            for category in guide.rendered_categories
        ],
    }
