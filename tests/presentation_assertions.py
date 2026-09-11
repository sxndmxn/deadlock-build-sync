"""Compare review records with the fields in a Steam build payload."""

from __future__ import annotations

import struct

from deadlock_build_sync.protobuf import parse_fields
from deadlock_build_sync.value_validation import (
    require_object_list,
    require_object_rows,
)


def _messages(payload: bytes, number: int) -> list[bytes]:
    return [
        field.value
        for field in parse_fields(payload)
        if field.number == number and isinstance(field.value, bytes)
    ]


def assert_presentation_payload(payload: bytes, record: dict[str, object]) -> None:
    fields = {field.number: field.value for field in parse_fields(payload)}
    assert fields[2] == record["hero_id"]
    assert fields[5] == str(record["name"]).encode()
    assert fields[6] == str(record["description"]).encode()
    assert [
        field.value for field in parse_fields(payload) if field.number == 11
    ] == record["tag_ids"]
    (details,) = _messages(payload, 10)
    categories = _messages(details, 1)
    for raw, category in zip(
        categories, require_object_rows(record["categories"]), strict=True
    ):
        _assert_category_payload(raw, category)
    abilities = _messages(details, 2)
    assert len(abilities) == bool(record["ability_order"])
    ability = abilities[0] if abilities else b""
    changes = _messages(ability, 1)
    counts: dict[object, int] = {}
    for index, (raw, ability_id) in enumerate(
        zip(changes, require_object_list(record["ability_order"]), strict=True)
    ):
        prior = counts.get(ability_id, 0)
        expected: dict[int, object] = {
            1: ability_id,
            2: 2 if prior == 0 else 1,
            3: (1 << 64) + (-1, -1, -2, -5)[prior],
        }
        if index == 0:
            expected[4] = str(record["ability_annotation"]).encode()
        assert {field.number: field.value for field in parse_fields(raw)} == expected
        counts[ability_id] = prior + 1


def _assert_category_payload(payload: bytes, record: dict[str, object]) -> None:
    assert {
        field.number: field.value
        for field in parse_fields(payload)
        if field.number != 1
    } == {
        2: str(record["name"]).encode(),
        3: str(record["description"]).encode(),
        4: struct.pack("<f", record["width"]),
        5: struct.pack("<f", record["height"]),
        6: record["optional"],
    }
    for raw, item in zip(
        _messages(payload, 1), require_object_rows(record["items"]), strict=True
    ):
        expected = {
            1: item["item_id"],
            2: str(item["annotation"]).encode(),
            3: item["required_flex_slots"],
            4: item["sell_priority"],
            5: item["imbue_target_ability_id"],
        }
        assert {field.number: field.value for field in parse_fields(raw)} == {
            key: value for key, value in expected.items() if value is not None
        }
