from __future__ import annotations

from decimal import Decimal

import pytest

from deadlock_build_sync.value_validation import (
    integer,
    number,
    object_dict,
    object_list,
    object_rows,
    require_object_dict,
    require_object_list,
    require_object_rows,
    text,
)


def test_object_containers_are_narrowed() -> None:
    row = {"value": 1}
    assert object_dict(row) is row
    assert object_dict({1: "value"}) is None
    assert object_list([row]) == [row]
    assert object_list((row,)) is None
    assert object_rows([row, "invalid"]) == [row]
    assert object_rows(row) is None


def test_scalar_conversion_is_explicit() -> None:
    assert integer("2") == 2
    assert integer(Decimal(28)) == 28
    assert integer(None, default=3) == 3
    assert number("2.5") == 2.5
    assert number(Decimal("2.5")) == 2.5
    assert text("value") == "value"
    with pytest.raises(TypeError, match="integer"):
        integer(value=True)
    with pytest.raises(TypeError, match="number"):
        number(None)
    with pytest.raises(TypeError, match="text"):
        text(1)


def test_required_containers_return_validated_values() -> None:
    mapping = {"value": 1}
    values = [1, "two"]
    rows = [{"value": 1}]

    assert require_object_dict(mapping) == mapping
    assert require_object_list(values) == values
    assert require_object_rows(rows) == rows


def test_required_containers_reject_invalid_values() -> None:
    with pytest.raises(TypeError, match="dictionary"):
        require_object_dict([])
    with pytest.raises(TypeError, match="list"):
        require_object_list({})
    with pytest.raises(TypeError, match="dictionaries"):
        require_object_rows([1])
