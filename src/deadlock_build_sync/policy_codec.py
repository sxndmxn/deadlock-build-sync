from __future__ import annotations

from typing import TYPE_CHECKING, cast

from cattrs import Converter
from cattrs.gen import make_dict_structure_fn, make_dict_unstructure_fn, override

from .policy import (
    Abstention,
    AbstentionReason,
    Branch,
    BuildPolicy,
    ClaimClass,
    CoreAlternativeCard,
    CounterCard,
    EvidenceClaim,
    Guard,
    GuardOperator,
    NodeKind,
    PolicyError,
    PolicyNode,
)
from .snapshot import EvidenceUnit
from .value_validation import object_dict, object_list

if TYPE_CHECKING:
    from collections.abc import Callable
    from enum import StrEnum

_converter = Converter(forbid_extra_keys=True, detailed_validation=True)


def _structure_int(value: object, _: type[int]) -> int:
    if type(value) is not int:
        raise TypeError("expected an integer")
    return value


def _structure_bool(value: object, _: type[bool]) -> bool:
    if type(value) is not bool:
        raise TypeError("expected a boolean")
    return value


def _structure_str(value: object, _: type[str]) -> str:
    if type(value) is not str:
        raise TypeError("expected a string")
    return value


def _structure_float(value: object, _: type[float]) -> float:
    if type(value) not in {int, float}:
        raise TypeError("expected a number")
    return float(cast("int | float", value))


def _structure_json_value(value: object, _: type[object]) -> object:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if (mapping := object_dict(value)) is not None:
        return {
            key: _structure_json_value(child, object) for key, child in mapping.items()
        }
    if (values := object_list(value)) is not None:
        return [_structure_json_value(child, object) for child in values]
    raise TypeError("expected a JSON value")


def _structure_enum(value: object, target: type[StrEnum]) -> StrEnum:
    return target(_structure_str(value, str))


_converter.register_structure_hook(int, _structure_int)
_converter.register_structure_hook(bool, _structure_bool)
_converter.register_structure_hook(str, _structure_str)
_converter.register_structure_hook(float, _structure_float)
_converter.register_structure_hook(object, _structure_json_value)
for _enum in (
    ClaimClass,
    EvidenceUnit,
    GuardOperator,
    NodeKind,
    AbstentionReason,
):
    _converter.register_structure_hook(_enum, _structure_enum)
    _converter.register_unstructure_hook(_enum, lambda value: value.value)


def _find_policy_error(error: BaseException) -> PolicyError | None:
    if isinstance(error, PolicyError):
        return error
    if isinstance(error, BaseExceptionGroup):
        for nested in error.exceptions:
            found = _find_policy_error(nested)
            if found is not None:
                return found
    return None


def _structure_with_context[T](
    value: object,
    hook: Callable[[dict[str, object]], T],
    context: str,
) -> T:
    mapping = object_dict(value)
    if mapping is None:
        raise PolicyError(f"malformed {context}: expected an object")
    try:
        return hook(mapping)
    except Exception as error:
        nested = _find_policy_error(error)
        if nested is not None and str(nested).startswith("malformed "):
            raise nested from error
        raise PolicyError(f"malformed {context}: {error}") from error


_structure_evidence_generated = make_dict_structure_fn(EvidenceClaim, _converter)
_unstructure_evidence = make_dict_unstructure_fn(
    EvidenceClaim,
    _converter,
    language_ceiling=override(unstruct_hook=sorted),
)


def _structure_evidence(value: object, _: type[EvidenceClaim]) -> EvidenceClaim:
    return _structure_with_context(
        value,
        _structure_evidence_generated,
        "evidence claim",
    )


_converter.register_structure_hook(EvidenceClaim, _structure_evidence)
_converter.register_unstructure_hook(EvidenceClaim, _unstructure_evidence)

_structure_guard_generated = make_dict_structure_fn(Guard, _converter)
_unstructure_guard = make_dict_unstructure_fn(Guard, _converter)


def _structure_guard(value: object, _: type[Guard]) -> Guard:
    return _structure_with_context(
        value,
        _structure_guard_generated,
        "policy guard",
    )


_converter.register_structure_hook(Guard, _structure_guard)
_converter.register_unstructure_hook(Guard, _unstructure_guard)


def _structure_branch_fields(value: dict[str, object]) -> Branch:
    unexpected = {str(key) for key in value if key not in {"next", "when", "priority"}}
    if unexpected:
        raise PolicyError(
            f"malformed policy branch: unexpected fields {sorted(unexpected)}"
        )
    next_id = _converter.structure(value["next"], str)
    raw_when = value["when"]
    raw_priority = value.get("priority")
    priority = (
        _converter.structure(raw_priority, int) if raw_priority is not None else None
    )
    if raw_when == "default":
        return Branch(next_id, priority=priority)
    if isinstance(raw_when, dict):
        return Branch(
            next_id,
            _converter.structure(raw_when, Guard),
            priority,
        )
    if isinstance(raw_when, list) and raw_when:
        guards = tuple(_converter.structure(item, Guard) for item in raw_when)
        return Branch(next_id, guards[0], priority, guards[1:])
    raise PolicyError("branch must use a guard or default")


def _structure_branch(value: object, _: type[Branch]) -> Branch:
    mapping = object_dict(value)
    if mapping is None:
        raise PolicyError("malformed policy branch: expected an object")
    try:
        return _structure_branch_fields(mapping)
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, PolicyError):
            raise
        raise PolicyError(f"malformed policy branch: {error}") from error


def _unstructure_branch(branch: Branch) -> dict[str, object]:
    guards = branch.guards
    when: str | dict[str, object] | list[dict[str, object]]
    if not guards:
        when = "default"
    elif len(guards) == 1:
        when = cast("dict[str, object]", _converter.unstructure(guards[0]))
    else:
        when = [
            cast("dict[str, object]", _converter.unstructure(guard)) for guard in guards
        ]
    return {"next": branch.next_id, "when": when, "priority": branch.priority}


_converter.register_structure_hook(Branch, _structure_branch)
_converter.register_unstructure_hook(Branch, _unstructure_branch)

_structure_node_generated = make_dict_structure_fn(
    PolicyNode,
    _converter,
    node_id=override(rename="id"),
    next_id=override(rename="next"),
)
_unstructure_node = make_dict_unstructure_fn(
    PolicyNode,
    _converter,
    node_id=override(rename="id"),
    next_id=override(rename="next"),
)


def _structure_node(value: object, _: type[PolicyNode]) -> PolicyNode:
    return _structure_with_context(
        value,
        _structure_node_generated,
        "policy node",
    )


_converter.register_structure_hook(PolicyNode, _structure_node)
_converter.register_unstructure_hook(PolicyNode, _unstructure_node)

_structure_counter_card_generated = make_dict_structure_fn(CounterCard, _converter)
_unstructure_counter_card = make_dict_unstructure_fn(CounterCard, _converter)


def _structure_counter_card(value: object, _: type[CounterCard]) -> CounterCard:
    return _structure_with_context(
        value,
        _structure_counter_card_generated,
        "counter card",
    )


_converter.register_structure_hook(CounterCard, _structure_counter_card)
_converter.register_unstructure_hook(CounterCard, _unstructure_counter_card)

_structure_core_alternative_generated = make_dict_structure_fn(
    CoreAlternativeCard, _converter
)
_unstructure_core_alternative = make_dict_unstructure_fn(
    CoreAlternativeCard, _converter
)


def _structure_core_alternative(
    value: object, _: type[CoreAlternativeCard]
) -> CoreAlternativeCard:
    return _structure_with_context(
        value,
        _structure_core_alternative_generated,
        "core alternative card",
    )


_converter.register_structure_hook(CoreAlternativeCard, _structure_core_alternative)
_converter.register_unstructure_hook(CoreAlternativeCard, _unstructure_core_alternative)

_structure_abstention_generated = make_dict_structure_fn(Abstention, _converter)
_unstructure_abstention = make_dict_unstructure_fn(Abstention, _converter)


def _structure_abstention(value: object, _: type[Abstention]) -> Abstention:
    return _structure_with_context(
        value,
        _structure_abstention_generated,
        "abstention",
    )


_converter.register_structure_hook(Abstention, _structure_abstention)
_converter.register_unstructure_hook(Abstention, _unstructure_abstention)

_structure_policy_generated = make_dict_structure_fn(BuildPolicy, _converter)
_unstructure_policy = make_dict_unstructure_fn(BuildPolicy, _converter)


def unstructure_evidence_claim(claim: EvidenceClaim) -> dict[str, object]:
    return _unstructure_evidence(claim)


def structure_evidence_claim(value: dict[str, object]) -> EvidenceClaim:
    return _structure_evidence(value, EvidenceClaim)


def unstructure_guard(guard: Guard) -> dict[str, object]:
    return _unstructure_guard(guard)


def structure_guard(value: dict[str, object]) -> Guard:
    return _structure_guard(value, Guard)


def unstructure_branch(branch: Branch) -> dict[str, object]:
    return _unstructure_branch(branch)


def structure_branch(value: dict[str, object]) -> Branch:
    return _structure_branch(value, Branch)


def unstructure_policy_node(node: PolicyNode) -> dict[str, object]:
    return _unstructure_node(node)


def structure_policy_node(value: dict[str, object]) -> PolicyNode:
    return _structure_node(value, PolicyNode)


def unstructure_counter_card(card: CounterCard) -> dict[str, object]:
    return _unstructure_counter_card(card)


def structure_counter_card(value: dict[str, object]) -> CounterCard:
    return _structure_counter_card(value, CounterCard)


def unstructure_build_policy(
    policy: BuildPolicy,
    *,
    include_policy_id: bool,
) -> dict[str, object]:
    payload = _unstructure_policy(policy)
    if include_policy_id:
        payload["policy_id"] = policy.policy_id
    return payload


def structure_build_policy(value: dict[str, object]) -> BuildPolicy:
    if not isinstance(value, dict):
        raise PolicyError("malformed build policy: expected an object")
    payload = dict(value)
    expected = payload.pop("policy_id", None)
    if expected is not None and type(expected) is not str:
        raise PolicyError("malformed build policy: policy_id must be a string")
    policy = _structure_with_context(
        payload,
        _structure_policy_generated,
        "build policy",
    )
    if expected is not None and expected != policy.policy_id:
        raise PolicyError("policy fingerprint does not match its contents")
    return policy
