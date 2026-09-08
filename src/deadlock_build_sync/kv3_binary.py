from __future__ import annotations

import struct
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

# Binary KV3 v4 serializer, ported from the MIT-licensed ValveResourceFormat
# BinaryKV3.Serialization implementation. The cache currently uses v5, but
# Source 2 readers accept the uncompressed v4 representation emitted here.
MAGIC_V4 = 0x4B563304
GENERIC_FORMAT = uuid.UUID("7412167c-06e9-4698-aff2-e63eb59037e7")
TRAILER = 0xFFEEDD00

NULL = 1
INT64 = 3
DOUBLE = 5
STRING = 6
BINARY_BLOB = 7
ARRAY = 8
OBJECT = 9
BOOLEAN_TRUE = 13
BOOLEAN_FALSE = 14
INT64_ZERO = 15
INT64_ONE = 16
DOUBLE_ZERO = 17
DOUBLE_ONE = 18

_PACKED_DOUBLE_ZERO = struct.pack("<d", 0.0)
_PACKED_DOUBLE_NEGATIVE_ZERO = struct.pack("<d", -0.0)
_PACKED_DOUBLE_ONE = struct.pack("<d", 1.0)
_INT32_FORMAT = "<i"
_UINT16_FORMAT = "<H"
_UINT32_FORMAT = "<I"
_UTF8 = "utf-8"


@dataclass
class _EncodingContext:
    strings: list[str] = field(default_factory=list)
    string_ids: dict[str, int] = field(default_factory=dict)
    bytes4: bytearray = field(
        default_factory=lambda: bytearray(struct.pack(_INT32_FORMAT, 0x0BADF00D))
    )
    bytes8: bytearray = field(default_factory=bytearray)
    types: bytearray = field(default_factory=bytearray)
    binary_blobs: bytearray = field(default_factory=bytearray)
    binary_blob_lengths: list[int] = field(default_factory=list)

    def string_id(self, value: str) -> int:
        if not value:
            return -1
        existing = self.string_ids.get(value)
        if existing is not None:
            return existing
        identifier = len(self.strings)
        self.string_ids[value] = identifier
        self.strings.append(value)
        return identifier


def _pack_into(buffer: bytearray, fmt: str, value: float) -> None:
    buffer.extend(struct.pack(fmt, value))


def _write_type(context: _EncodingContext, node_type: int) -> None:
    context.types.append(node_type)


def _write_property(context: _EncodingContext, name: str, value: object) -> None:
    _pack_into(context.bytes4, _INT32_FORMAT, context.string_id(name))
    _write_value(context, value)


def _write_object(context: _EncodingContext, value: dict[str, object]) -> None:
    _write_type(context, OBJECT)
    _pack_into(context.bytes4, _INT32_FORMAT, len(value))
    for name, child in value.items():
        _write_property(context, str(name), child)


def _write_integer(context: _EncodingContext, value: int) -> None:
    if value == 0:
        _write_type(context, INT64_ZERO)
    elif value == 1:
        _write_type(context, INT64_ONE)
    else:
        if not -(1 << 63) <= value < (1 << 63):
            raise OverflowError(f"KV3 integer is outside signed 64-bit range: {value}")
        _write_type(context, INT64)
        _pack_into(context.bytes8, "<q", value)


def _write_float(context: _EncodingContext, value: float) -> None:
    packed = struct.pack("<d", value)
    if packed in {_PACKED_DOUBLE_ZERO, _PACKED_DOUBLE_NEGATIVE_ZERO}:
        _write_type(context, DOUBLE_ZERO)
    elif packed == _PACKED_DOUBLE_ONE:
        _write_type(context, DOUBLE_ONE)
    else:
        _write_type(context, DOUBLE)
        _pack_into(context.bytes8, "<d", value)


def _write_string(context: _EncodingContext, value: str) -> None:
    _write_type(context, STRING)
    _pack_into(context.bytes4, _INT32_FORMAT, context.string_id(value))


def _write_blob(
    context: _EncodingContext, value: bytes | bytearray | memoryview
) -> None:
    blob = bytes(value)
    _write_type(context, BINARY_BLOB)
    context.binary_blob_lengths.append(len(blob))
    context.binary_blobs.extend(blob)


def _write_array(context: _EncodingContext, value: Sequence[object]) -> None:
    _write_type(context, ARRAY)
    _pack_into(context.bytes4, _INT32_FORMAT, len(value))
    for child in value:
        _write_value(context, child)


def _write_value(context: _EncodingContext, value: object) -> None:
    if value is None:
        _write_type(context, NULL)
    elif isinstance(value, bool):
        _write_type(context, BOOLEAN_TRUE if value else BOOLEAN_FALSE)
    elif isinstance(value, int):
        _write_integer(context, value)
    elif isinstance(value, float):
        _write_float(context, value)
    elif isinstance(value, str):
        _write_string(context, value)
    elif isinstance(value, (bytes, bytearray, memoryview)):
        _write_blob(context, value)
    elif isinstance(value, dict):
        _write_object(context, {str(name): child for name, child in value.items()})
    elif isinstance(value, (list, tuple)):
        _write_array(context, value)
    else:
        raise TypeError(f"unsupported KV3 value: {type(value).__name__}")


def _align(buffer: bytearray, alignment: int) -> None:
    padding = (-len(buffer)) % alignment
    if padding:
        buffer.extend(b"\0" * padding)


def encode_binary_v4(root: dict[str, object]) -> bytes:
    if not isinstance(root, dict):
        raise TypeError("KV3 root must be an object")
    context = _EncodingContext()
    _write_object(context, root)
    context.bytes4[0:4] = struct.pack(_INT32_FORMAT, len(context.strings))

    data = bytearray(context.bytes4)
    _align(data, 8)
    data.extend(context.bytes8)

    strings = bytearray()
    for value in context.strings:
        strings.extend(value.encode(_UTF8))
        strings.append(0)
    data.extend(strings)
    data.extend(context.types)
    types_and_strings_size = len(strings) + len(context.types)

    if context.binary_blob_lengths:
        for length in context.binary_blob_lengths:
            _pack_into(data, _INT32_FORMAT, length)
        _pack_into(data, _UINT32_FORMAT, TRAILER)
    else:
        _pack_into(data, _UINT32_FORMAT, TRAILER)

    header = bytearray()
    _pack_into(header, _UINT32_FORMAT, MAGIC_V4)
    header.extend(GENERIC_FORMAT.bytes_le)
    _pack_into(header, _INT32_FORMAT, 0)
    _pack_into(header, _UINT16_FORMAT, 0)
    _pack_into(header, _UINT16_FORMAT, 0)
    _pack_into(header, _INT32_FORMAT, 0)
    _pack_into(header, _INT32_FORMAT, len(context.bytes4) // 4)
    _pack_into(header, _INT32_FORMAT, len(context.bytes8) // 8)
    _pack_into(header, _INT32_FORMAT, types_and_strings_size)
    _pack_into(header, _UINT16_FORMAT, 0)
    _pack_into(header, _UINT16_FORMAT, 0)
    _pack_into(header, _INT32_FORMAT, len(data))
    _pack_into(header, _INT32_FORMAT, len(data))
    _pack_into(header, _INT32_FORMAT, len(context.binary_blob_lengths))
    _pack_into(header, _INT32_FORMAT, len(context.binary_blobs))
    _pack_into(header, _INT32_FORMAT, 0)
    _pack_into(header, _INT32_FORMAT, 0)

    output = header + data
    if context.binary_blob_lengths:
        output.extend(context.binary_blobs)
        _pack_into(output, _UINT32_FORMAT, TRAILER)
    return bytes(output)
