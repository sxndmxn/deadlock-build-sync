import hashlib
import struct
from typing import cast

import pytest

from deadlock_build_sync import kv3_binary


def test_context_assigns_stable_string_ids() -> None:
    context = kv3_binary._EncodingContext()

    assert context.string_id("") == -1
    assert context.string_id("alpha") == 0
    assert context.string_id("alpha") == 0
    assert context.string_id("beta") == 1
    assert context.strings == ["alpha", "beta"]
    assert context.string_ids == {"alpha": 0, "beta": 1}


@pytest.mark.parametrize(
    ("value", "node_type", "packed"),
    [
        (0, kv3_binary.INT64_ZERO, b""),
        (1, kv3_binary.INT64_ONE, b""),
        (-2, kv3_binary.INT64, struct.pack("<q", -2)),
        (2, kv3_binary.INT64, struct.pack("<q", 2)),
        (-(1 << 63), kv3_binary.INT64, struct.pack("<q", -(1 << 63))),
        ((1 << 63) - 1, kv3_binary.INT64, struct.pack("<q", (1 << 63) - 1)),
    ],
)
def test_integer_writer_uses_the_smallest_valid_form(
    value: int,
    node_type: int,
    packed: bytes,
) -> None:
    context = kv3_binary._EncodingContext()

    kv3_binary._write_integer(context, value)

    assert context.types == bytearray([node_type])
    assert context.bytes8 == packed


@pytest.mark.parametrize("value", [-(1 << 63) - 1, 1 << 63])
def test_integer_writer_rejects_values_outside_int64(value: int) -> None:
    with pytest.raises(
        OverflowError,
        match=f"^KV3 integer is outside signed 64-bit range: {value}$",
    ):
        kv3_binary._write_integer(kv3_binary._EncodingContext(), value)


@pytest.mark.parametrize(
    ("value", "node_type", "packed"),
    [
        (0.0, kv3_binary.DOUBLE_ZERO, b""),
        (-0.0, kv3_binary.DOUBLE_ZERO, b""),
        (1.0, kv3_binary.DOUBLE_ONE, b""),
        (-1.0, kv3_binary.DOUBLE, struct.pack("<d", -1.0)),
        (2.5, kv3_binary.DOUBLE, struct.pack("<d", 2.5)),
    ],
)
def test_float_writer_preserves_special_and_regular_values(
    value: float,
    node_type: int,
    packed: bytes,
) -> None:
    context = kv3_binary._EncodingContext()

    kv3_binary._write_float(context, value)

    assert context.types == bytearray([node_type])
    assert context.bytes8 == packed


def test_property_object_string_and_array_writers_record_each_field() -> None:
    context = kv3_binary._EncodingContext()

    kv3_binary._write_object(context, {"name": "value", "rows": [0, 1]})

    assert context.strings == ["name", "value", "rows"]
    assert context.string_ids == {"name": 0, "value": 1, "rows": 2}
    assert context.bytes4 == bytearray(
        struct.pack("<i", 0x0BADF00D)
        + struct.pack("<i", 2)
        + struct.pack("<i", 0)
        + struct.pack("<i", 1)
        + struct.pack("<i", 2)
        + struct.pack("<i", 2)
    )
    assert context.types == bytearray([
        kv3_binary.OBJECT,
        kv3_binary.STRING,
        kv3_binary.ARRAY,
        kv3_binary.INT64_ZERO,
        kv3_binary.INT64_ONE,
    ])

    empty_name = kv3_binary._EncodingContext()
    kv3_binary._write_property(empty_name, "", 0)
    assert empty_name.bytes4[-4:] == struct.pack("<i", -1)


def test_value_writer_supports_each_value_kind() -> None:
    context = kv3_binary._EncodingContext()
    values: tuple[object, ...] = (
        None,
        False,
        True,
        2,
        2.5,
        "text",
        b"bytes",
        bytearray(b"array"),
        memoryview(b"view"),
        {1: "mapped"},
        [0],
        (1,),
    )

    for value in values:
        kv3_binary._write_value(context, value)

    assert context.types == bytearray([
        kv3_binary.NULL,
        kv3_binary.BOOLEAN_FALSE,
        kv3_binary.BOOLEAN_TRUE,
        kv3_binary.INT64,
        kv3_binary.DOUBLE,
        kv3_binary.STRING,
        kv3_binary.BINARY_BLOB,
        kv3_binary.BINARY_BLOB,
        kv3_binary.BINARY_BLOB,
        kv3_binary.OBJECT,
        kv3_binary.STRING,
        kv3_binary.ARRAY,
        kv3_binary.INT64_ZERO,
        kv3_binary.ARRAY,
        kv3_binary.INT64_ONE,
    ])
    assert context.binary_blob_lengths == [5, 5, 4]
    assert context.binary_blobs == b"bytesarrayview"
    assert context.strings == ["text", "1", "mapped"]


def test_value_writer_rejects_an_unsupported_type() -> None:
    with pytest.raises(TypeError, match=r"^unsupported KV3 value: set$"):
        kv3_binary._write_value(kv3_binary._EncodingContext(), {1, 2})


@pytest.mark.parametrize(
    ("initial", "alignment", "expected"),
    [
        (b"", 4, b""),
        (b"a", 4, b"a\0\0\0"),
        (b"abcd", 4, b"abcd"),
        (b"abcde", 8, b"abcde\0\0\0"),
    ],
)
def test_alignment_adds_only_required_padding(
    initial: bytes,
    alignment: int,
    expected: bytes,
) -> None:
    buffer = bytearray(initial)

    kv3_binary._align(buffer, alignment)

    assert buffer == expected


def test_encoder_has_stable_output_for_all_supported_value_kinds() -> None:
    roots: list[dict[str, object]] = [
        {},
        {
            "none": None,
            "false": False,
            "true": True,
            "zero": 0,
            "one": 1,
            "minus": -2,
            "maximum": (1 << 63) - 1,
            "float_zero": 0.0,
            "float_negative_zero": -0.0,
            "float_one": 1.0,
            "float_other": 2.5,
            "empty": "",
            "text": "repeat",
            "again": "repeat",
            "blob": b"\x00\x01",
            "bytearray": bytearray(b"ab"),
            "view": memoryview(b"cd"),
            "mapping": {1: "x"},
            "list": [None, 0, 1, 2],
            "tuple": (False, True),
        },
    ]

    outputs = [kv3_binary.encode_binary_v4(root) for root in roots]

    assert [(len(value), hashlib.sha256(value).hexdigest()) for value in outputs] == [
        (85, "e2f9fc9902dfeb8c14095d02749d52cb9b2e05213bc48ec78bf829f99b2f852f"),
        (437, "22a6ac8c4ab9e7e990a96071bd813035a5a70f575d1942a3b1e01858a3f2dd22"),
    ]


def test_encoder_rejects_a_non_object_root() -> None:
    root = cast("dict[str, object]", [])

    with pytest.raises(TypeError, match=r"^KV3 root must be an object$"):
        kv3_binary.encode_binary_v4(root)
