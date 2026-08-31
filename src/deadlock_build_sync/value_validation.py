"""Narrow untrusted container values at I/O boundaries."""

from __future__ import annotations

from decimal import Decimal
from typing import cast


def object_dict(value: object) -> dict[str, object] | None:
    """Return a string-keyed dictionary when the value has that shape.

    Returns:
        The narrowed dictionary, or ``None`` for another shape.

    """
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        return None
    return cast("dict[str, object]", value)


def object_list(value: object) -> list[object] | None:
    """Return a list with unknown elements after validating the container.

    Returns:
        The narrowed list, or ``None`` for another shape.

    """
    if not isinstance(value, list):
        return None
    return cast("list[object]", value)


def object_rows(value: object) -> list[dict[str, object]] | None:
    """Return all string-keyed dictionary rows from a validated list.

    Returns:
        The narrowed rows, or ``None`` when the outer value is not a list.

    """
    rows = object_list(value)
    if rows is None:
        return None
    return [row for value in rows if (row := object_dict(value)) is not None]


def require_object_dict(value: object) -> dict[str, object]:
    """Require a string-keyed dictionary.

    Returns:
        The validated dictionary.

    Raises:
        TypeError: If the value is not a string-keyed dictionary.

    """
    result = object_dict(value)
    if result is None:
        raise TypeError("expected a string-keyed dictionary")
    return result


def require_object_list(value: object) -> list[object]:
    """Require a list.

    Returns:
        The validated list.

    Raises:
        TypeError: If the value is not a list.

    """
    result = object_list(value)
    if result is None:
        raise TypeError("expected a list")
    return result


def require_object_rows(value: object) -> list[dict[str, object]]:
    """Require a list that contains only string-keyed dictionaries.

    Returns:
        The validated row list.

    Raises:
        TypeError: If the value does not contain only valid dictionaries.

    """
    values = require_object_list(value)
    rows = object_rows(values)
    if rows is None or len(rows) != len(values):
        raise TypeError("expected a list of string-keyed dictionaries")
    return rows


def integer(value: object, *, default: int | None = None) -> int:
    """Convert a basic scalar to an integer.

    Args:
        value: The untrusted scalar.
        default: A value used for ``None`` and empty strings.

    Returns:
        The converted integer.

    Raises:
        TypeError: If the value is not a supported scalar.

    """
    if value is None or (isinstance(value, str) and not value):
        if default is not None:
            return default
        raise TypeError("expected an integer")
    if isinstance(value, bool):
        raise TypeError("expected an integer")
    if isinstance(value, int | float | Decimal | str | bytes | bytearray):
        return int(value)
    raise TypeError("expected an integer")


def number(value: object) -> float:
    """Convert a basic scalar to a float.

    Returns:
        The converted number.

    Raises:
        TypeError: If the value is not a supported scalar.

    """
    if isinstance(value, bool):
        raise TypeError("expected a number")
    if isinstance(value, int | float | Decimal | str | bytes | bytearray):
        return float(value)
    raise TypeError("expected a number")


def text(value: object) -> str:
    """Require a string value.

    Returns:
        The validated string.

    Raises:
        TypeError: If the value is not a string.

    """
    if not isinstance(value, str):
        raise TypeError("expected text")
    return value
