import hashlib

import pytest

from deadlock_build_sync import protobuf
from deadlock_build_sync.ability_order import AbilityPath
from deadlock_build_sync.presentation import (
    LEGACY_MANAGED_MARKER,
    MANAGED_MARKER,
    BuildPresentation,
)


def _presentation(ability_ids: tuple[int, ...] | None) -> BuildPresentation:
    ability_path = (
        AbilityPath(ability_ids, 20, 12, 8, 40) if ability_ids is not None else None
    )
    return BuildPresentation(
        12,
        "Build",
        (1, 2, 3),
        f"{MANAGED_MARKER}\nBuild path: default.",
        (),
        ability_path,
    )


@pytest.mark.parametrize(
    ("value", "encoded"),
    [
        (-1, b"\xff\xff\xff\xff\xff\xff\xff\xff\xff\x01"),
        (0, b"\x00"),
        (1, b"\x01"),
        (127, b"\x7f"),
        (128, b"\x80\x01"),
        (300, b"\xac\x02"),
        ((1 << 64) - 1, b"\xff\xff\xff\xff\xff\xff\xff\xff\xff\x01"),
    ],
)
def test_varint_encoder_preserves_boundaries(value: int, encoded: bytes) -> None:
    assert protobuf.encode_varint(value) == encoded


def test_field_encoders_preserve_wire_types_and_empty_rules() -> None:
    assert protobuf.varint_field(3, None) == b""
    assert protobuf.varint_field(3, 150) == b"\x18\x96\x01"
    assert protobuf.bool_field(3, value=None) == b""
    assert protobuf.bool_field(3, value=False) == b"\x18\x00"
    assert protobuf.bool_field(3, value=True) == b"\x18\x01"
    assert protobuf.float_field(2, None) == b""
    assert protobuf.float_field(2, 1.5) == b"\x15\x00\x00\xc0\x3f"
    assert protobuf.bytes_field(2, b"ab") == b"\x12\x02ab"
    assert protobuf.string_field(1, None) == b""
    assert protobuf.string_field(1, "é") == b"\x0a\x02\xc3\xa9"
    assert protobuf.message_field(1, b"") == b""
    assert protobuf.message_field(1, b"x") == b"\x0a\x01x"


def test_varint_reader_honors_offset_and_reports_bad_input() -> None:
    assert protobuf.read_varint(b"\xff\xac\x02x", 1) == (300, 3)

    with pytest.raises(ValueError, match=r"^truncated protobuf varint$"):
        protobuf.read_varint(b"", 0)
    with pytest.raises(ValueError, match=r"^truncated protobuf varint$"):
        protobuf.read_varint(b"\x80", 0)
    with pytest.raises(ValueError, match=r"^protobuf varint is too long$"):
        protobuf.read_varint(b"\x80" * 10 + b"\x00", 0)


def test_field_parser_reads_each_supported_wire_type() -> None:
    payload = b"\x08\x96\x01" + b"\x11abcdefgh" + b"\x1a\x02hi" + b"\x25wxyz"

    assert list(protobuf.parse_fields(payload)) == [
        protobuf.ProtoField(1, 0, 150),
        protobuf.ProtoField(2, 1, b"abcdefgh"),
        protobuf.ProtoField(3, 2, b"hi"),
        protobuf.ProtoField(4, 5, b"wxyz"),
    ]


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b"\x0b", "unsupported protobuf wire type 3"),
        (b"\x09short", "truncated protobuf field"),
        (b"\x0a\x03ab", "truncated protobuf field"),
        (b"\x0dabc", "truncated protobuf field"),
    ],
)
def test_field_parser_rejects_malformed_fields(payload: bytes, message: str) -> None:
    with pytest.raises(ValueError, match=f"^{message}$"):
        list(protobuf.parse_fields(payload))


def test_build_extractor_requires_expected_nested_fields() -> None:
    build = protobuf.varint_field(2, 12) + protobuf.string_field(5, "Build")
    wrong_nested = protobuf.varint_field(2, 12)
    wrapper = (
        protobuf.varint_field(1, 7)
        + protobuf.bytes_field(1, wrong_nested)
        + protobuf.bytes_field(1, build)
    )

    assert protobuf.extract_hero_build(wrapper) == build
    assert protobuf.extract_hero_build(wrong_nested) == wrong_nested


def test_build_extractor_ignores_an_inconsistent_length_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fields(value: object) -> object:
        if isinstance(value, bytes):
            return iter([protobuf.ProtoField(1, 2, 7)])
        raise TypeError("nested value is not bytes")

    monkeypatch.setattr(
        protobuf,
        "parse_fields",
        fields,
    )

    assert protobuf.extract_hero_build(b"wrapper") == b"wrapper"


def test_metadata_parser_preserves_supported_fields_and_tags() -> None:
    build = (
        protobuf.varint_field(1, 34)
        + protobuf.varint_field(2, 12)
        + protobuf.varint_field(3, 56)
        + protobuf.float_field(4, 1.5)
        + protobuf.string_field(5, "Build")
        + protobuf.bytes_field(6, b"bad\xfftext")
        + protobuf.varint_field(8, 2)
        + protobuf.varint_field(11, 7)
        + protobuf.varint_field(11, 8)
        + protobuf.varint_field(13, 90)
    )

    assert protobuf.hero_build_metadata(build) == protobuf.HeroBuildMetadata(
        build_id=34,
        hero_id=12,
        author_account_id=56,
        name="Build",
        description="bad�text",
        version=2,
        publish_timestamp=90,
        tag_ids=(7, 8),
    )


def test_metadata_recorder_ignores_mismatched_wire_values() -> None:
    values: dict[int, int | str] = {}
    tag_ids: list[int] = []

    for field in (
        protobuf.ProtoField(4, 0, b"not-an-int"),
        protobuf.ProtoField(4, 2, 7),
        protobuf.ProtoField(7, 2, b"not-text-metadata"),
    ):
        protobuf._record_metadata_field(field, values, tag_ids)

    assert values == {}
    assert tag_ids == []


def test_ability_order_records_each_upgrade_cost() -> None:
    payload = protobuf._encode_ability_order(_presentation((10, 10, 10, 10)))
    changes = [
        list(protobuf.parse_fields(field.value))
        for field in protobuf.parse_fields(payload)
        if isinstance(field.value, bytes)
    ]

    assert [
        (change[0].value, change[1].value, change[2].value) for change in changes
    ] == [
        (10, 2, (1 << 64) - 1),
        (10, 1, (1 << 64) - 1),
        (10, 1, (1 << 64) - 2),
        (10, 1, (1 << 64) - 5),
    ]
    assert changes[0][3].value == (
        b"State-composed observed default \xe2\x80\xa2 tail support n=20 "
        b"\xe2\x80\xa2 observational."
    )
    assert all(len(change) == 3 for change in changes[1:])
    assert protobuf._encode_ability_order(_presentation(None)) == b""


def test_ability_order_rejects_a_fifth_purchase() -> None:
    with pytest.raises(
        ValueError, match="ability 10 appears too often in ability path"
    ):
        protobuf._encode_ability_order(_presentation((10, 10, 10, 10, 10)))


def test_hero_build_encoder_has_stable_output() -> None:
    build = protobuf.encode_hero_build(
        _presentation((10, 10, 10, 10)),
        build_id=34,
        account_id=56,
        timestamp=78,
    )

    assert len(build) == 224
    assert hashlib.sha256(build).hexdigest() == (
        "763c8b220fbc9d745b6534f7202b107399b9e3733662e00101c6b39d42320110"
    )


def test_managed_identity_requires_owner_marker_and_optional_path() -> None:
    current = protobuf.HeroBuildMetadata(
        1,
        12,
        56,
        "Build",
        f"{MANAGED_MARKER}\nBuild path: default.",
        0,
        None,
        (),
    )
    legacy = protobuf.HeroBuildMetadata(
        1,
        12,
        56,
        "Build",
        LEGACY_MANAGED_MARKER,
        0,
        None,
        (),
    )

    assert protobuf.managed_build_path(current) == "default"
    assert protobuf.managed_build_path(legacy) is None
    assert protobuf.is_managed_build(current, hero_id=12, account_id=56)
    assert protobuf.is_managed_build(
        current,
        hero_id=12,
        account_id=56,
        path_id="default",
    )
    assert protobuf.is_managed_build(legacy, hero_id=12, account_id=56)
    assert not protobuf.is_managed_build(current, hero_id=13, account_id=56)
    assert not protobuf.is_managed_build(current, hero_id=12, account_id=57)
    assert not protobuf.is_managed_build(
        current,
        hero_id=12,
        account_id=56,
        path_id="other",
    )
    assert not protobuf.is_managed_build(
        protobuf.HeroBuildMetadata(1, 12, 56, "Build", None, 0, None, ()),
        hero_id=12,
        account_id=56,
    )
