from __future__ import annotations

from typing import cast

from .artifacts import ArtifactError
from .build_evidence_situational import parse_situational_branch
from .build_evidence_types import (
    MAX_SITUATIONAL_BRANCHES,
    SEQUENCE_LEVELS,
    SEQUENCE_POLICY_VERSION,
    SITUATIONAL_POLICY_VERSION,
    THREAT_CLASSES,
    SequencePolicy,
    SequenceTransition,
    SituationalBranch,
    SituationalPolicy,
)
from .build_evidence_values import (
    _require_integer,
)
from .value_validation import object_dict

type _SequencePolicyDocument = dict[str, object]
type _SituationalPolicyDocument = dict[str, object]


def _parse_sequence_transition(value: object, hero_id: int) -> SequenceTransition:
    if not isinstance(value, dict):
        raise ArtifactError(f"hero {hero_id} has a malformed sequence transition")
    level = value.get("level")
    if level not in SEQUENCE_LEVELS:
        raise ArtifactError(f"hero {hero_id} has an invalid sequence backoff level")
    support = _require_integer(value.get("support"), "transition support", minimum=1)
    context_support = _require_integer(
        value.get("context_support"),
        "transition context support",
        minimum=support,
    )
    return SequenceTransition(
        level=str(level),
        first_item_id=_require_integer(value.get("first_item_id"), "first item id"),
        previous_item_id=_require_integer(
            value.get("previous_item_id"), "previous item id"
        ),
        position=_require_integer(value.get("position"), "purchase position"),
        next_item_id=_require_integer(
            value.get("next_item_id"), "next item id", minimum=1
        ),
        support=support,
        context_support=context_support,
    )


def _parse_sequence_policy(value: object, hero_id: int) -> SequencePolicy:
    if not isinstance(value, dict) or value.get("version") != SEQUENCE_POLICY_VERSION:
        raise ArtifactError(f"hero {hero_id} has no supported sequence policy")
    data = cast("_SequencePolicyDocument", value)
    raw_path = data.get("component_expanded_default_path")
    raw_transitions = data.get("transitions")
    evaluation = object_dict(data.get("evaluation"))
    production_model = data.get("production_model")
    if (
        not isinstance(raw_path, list)
        or not raw_path
        or not isinstance(raw_transitions, list)
        or (not raw_transitions and production_model not in {"pairwise", "beam16"})
        or evaluation is None
        or production_model not in {"deterministic_backoff", "pairwise", "beam16"}
    ):
        raise ArtifactError(f"hero {hero_id} has an incomplete sequence policy")
    path = tuple(
        _require_integer(item_id, "default path item id", minimum=1)
        for item_id in raw_path
    )
    if production_model not in {"pairwise", "beam16"} and len(path) != len(set(path)):
        raise ArtifactError(f"hero {hero_id} default path repeats an item")
    minimum_support = _require_integer(
        data.get("minimum_support"), "sequence minimum support", minimum=20
    )
    transitions = tuple(
        _parse_sequence_transition(row, hero_id) for row in raw_transitions
    )
    if any(row.support < minimum_support for row in transitions):
        raise ArtifactError(f"hero {hero_id} has a weak sequence transition")
    return SequencePolicy(
        path,
        transitions,
        minimum_support,
        str(production_model),
        evaluation,
    )


def _parse_situational_branch(value: object, hero_id: int) -> SituationalBranch:
    return parse_situational_branch(value, hero_id)


def _parse_situational_policy(value: object, hero_id: int) -> SituationalPolicy:
    if (
        not isinstance(value, dict)
        or value.get("version") != SITUATIONAL_POLICY_VERSION
    ):
        raise ArtifactError(f"hero {hero_id} has no supported situational policy")
    data = cast("_SituationalPolicyDocument", value)
    branches = data.get("branches")
    abstentions = data.get("abstentions")
    vocabulary = data.get("threat_vocabulary")
    if (
        not isinstance(branches, list)
        or not isinstance(abstentions, list)
        or vocabulary != sorted(THREAT_CLASSES)
    ):
        raise ArtifactError(f"hero {hero_id} has an incomplete situational policy")
    if len(branches) > MAX_SITUATIONAL_BRANCHES:
        raise ArtifactError(f"hero {hero_id} has too many situational branches")
    if not all(isinstance(reason, str) and reason.strip() for reason in abstentions):
        raise ArtifactError(f"hero {hero_id} has an invalid situational abstention")
    admitted = tuple(_parse_situational_branch(row, hero_id) for row in branches)
    identities = [
        (branch.threat, branch.enemy_hero_id, branch.item_id) for branch in admitted
    ]
    if len(identities) != len(set(identities)):
        raise ArtifactError(f"hero {hero_id} has duplicate situational branches")
    item_ids = [branch.item_id for branch in admitted]
    if len(item_ids) != len(set(item_ids)):
        raise ArtifactError(f"hero {hero_id} repeats a situational item")
    if not admitted and not abstentions:
        raise ArtifactError(f"hero {hero_id} has no situational result")
    return SituationalPolicy(
        admitted,
        tuple(cast("list[str]", abstentions)),
    )
