from __future__ import annotations

import math

from .artifacts import ArtifactError
from .value_validation import object_dict


def _require_integer(
    value: object,
    label: str,
    *,
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < minimum
        or (maximum is not None and value > maximum)
    ):
        raise ArtifactError(f"build evidence has invalid {label}")
    return value


def _require_float(
    value: object, label: str, *, minimum: float = 0.0, maximum: float | None = None
) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or float(value) < minimum
        or (maximum is not None and float(value) > maximum)
    ):
        raise ArtifactError(f"build evidence has invalid {label}")
    return float(value)


def _require_finite_float(value: object, label: str) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
    ):
        raise ArtifactError(f"build evidence has invalid {label}")
    return float(value)


def _require_boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ArtifactError(f"build evidence has invalid {label}")
    return value


def _parse_optional_float(value: object, label: str) -> float | None:
    return None if value is None else _require_float(value, label)


def _require_sha256(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ArtifactError(f"build evidence has invalid {label}")
    return value


def _require_evidence_document(value: object, error_message: str) -> dict[str, object]:
    document = object_dict(value)
    if document is None:
        raise ArtifactError(error_message)
    return document
