"""Validation for player-facing optional item cards."""

from .policy import PolicyError
from .purchase_guide import (
    CONDITIONAL_ANNOTATION_LABELS,
    conditional_item_annotation,
)

MAX_ANNOTATION_BYTES = 240


def validate_optional_annotation(annotation: str) -> None:
    """Enforce the fixed five-line conditional decision contract.

    Raises:
        PolicyError: If a conditional tile cannot be executed from its annotation.

    """
    lines = annotation.splitlines()
    if len(lines) != len(CONDITIONAL_ANNOTATION_LABELS):
        raise PolicyError("optional annotation must contain five decision lines")
    values: dict[str, str] = {}
    for expected, line in zip(CONDITIONAL_ANNOTATION_LABELS, lines, strict=True):
        prefix = f"{expected}: "
        if not line.startswith(prefix):
            raise PolicyError("optional annotation labels are missing or out of order")
        values[expected] = line.removeprefix(prefix)
    try:
        rebuilt = conditional_item_annotation(
            vs=values["VS"],
            why=values["WHY"],
            swap=values["SWAP"],
            when=values["WHEN"],
            skip=values["SKIP"],
        )
    except ValueError as error:
        raise PolicyError(f"optional annotation is invalid: {error}") from error
    if rebuilt != annotation or len(annotation.encode("utf-8")) > MAX_ANNOTATION_BYTES:
        raise PolicyError("optional annotation is not in canonical form")
