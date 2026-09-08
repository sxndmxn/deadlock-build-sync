from __future__ import annotations

import pytest

from deadlock_build_sync import policy_codec
from deadlock_build_sync.policy import Branch, Guard, GuardOperator, PolicyError
from tests.policy_fixtures import branching_policy


def test_codec_primitive_and_json_structure_is_strict() -> None:
    boolean: object = True
    with pytest.raises(TypeError):
        policy_codec._structure_int(boolean, int)
    with pytest.raises(TypeError):
        policy_codec._structure_bool(1, bool)
    with pytest.raises(TypeError):
        policy_codec._structure_str(1, str)
    assert policy_codec._structure_float(1, float) == 1.0
    with pytest.raises(TypeError):
        policy_codec._structure_float("1", float)
    assert policy_codec._structure_json_value({"a": [1, True, None]}, object) == {
        "a": [1, True, None]
    }
    with pytest.raises(TypeError):
        policy_codec._structure_json_value({1}, object)


def test_codec_finds_nested_policy_errors_and_preserves_malformed_context() -> None:
    nested = ExceptionGroup("group", [ValueError("bad"), PolicyError("policy")])
    assert str(policy_codec._find_policy_error(nested)) == "policy"
    assert policy_codec._find_policy_error(ValueError("bad")) is None

    def malformed(_value: dict[str, object]) -> object:
        raise PolicyError("malformed inner")

    def invalid(_value: dict[str, object]) -> object:
        raise ValueError("bad")

    with pytest.raises(PolicyError, match="expected an object"):
        policy_codec._structure_with_context([], invalid, "test")
    with pytest.raises(PolicyError, match="malformed inner"):
        policy_codec._structure_with_context({}, malformed, "test")
    with pytest.raises(PolicyError, match="malformed test"):
        policy_codec._structure_with_context({}, invalid, "test")


def test_codec_branches_cover_default_single_multiple_and_invalid_forms() -> None:
    guard = Guard("level", GuardOperator.AT_LEAST, 1)
    default = Branch("end")
    single = Branch("end", guard)
    multiple = Branch(
        "end",
        guard,
        additional_guards=(Guard("level", GuardOperator.AT_MOST, 5),),
    )
    for branch in (default, single, multiple):
        assert (
            policy_codec.structure_branch(policy_codec.unstructure_branch(branch))
            == branch
        )

    with pytest.raises(PolicyError, match="expected an object"):
        policy_codec._structure_branch([], Branch)
    with pytest.raises(PolicyError, match="unexpected fields"):
        policy_codec.structure_branch({"next": "end", "when": "default", "bad": 1})
    with pytest.raises(PolicyError, match="guard or default"):
        policy_codec.structure_branch({"next": "end", "when": []})
    with pytest.raises(PolicyError, match="malformed policy branch"):
        policy_codec.structure_branch({"when": "default"})


def test_codec_policy_id_type_and_optional_fingerprint_are_strict() -> None:
    policy = branching_policy()
    payload = policy_codec.unstructure_build_policy(policy, include_policy_id=False)
    assert "policy_id" not in payload
    payload["policy_id"] = 1
    with pytest.raises(PolicyError, match="policy_id must be a string"):
        policy_codec.structure_build_policy(payload)
