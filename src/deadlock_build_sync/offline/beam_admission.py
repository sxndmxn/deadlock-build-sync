"""Check complete guide coverage before accepting a beam replacement."""

from __future__ import annotations

from typing import TYPE_CHECKING

from deadlock_build_sync.artifacts import ArtifactError
from deadlock_build_sync.build_evidence import select_hero_build
from deadlock_build_sync.build_evidence_path import _parse_build_path
from deadlock_build_sync.mechanics import (
    MechanicsError,
    build_hero_mechanics,
    parse_ability_definitions,
)
from deadlock_build_sync.purchase_guide import build_purchase_guide_from_evidence
from deadlock_build_sync.service_inputs import _find_invalid_imbue_target
from deadlock_build_sync.value_validation import integer

if TYPE_CHECKING:
    from .beam_nomination import BeamDiscoveryJob


def complete_guide_rejection(
    build: dict[str, object], job: BeamDiscoveryJob, group: str
) -> str | None:
    build["guide_group_id"] = group
    try:
        evidence = _parse_build_path(
            build, hero_id=integer(job.hero["id"]), hero_name=str(job.hero["name"])
        )
        selected = select_hero_build(evidence, job.context.normal_assets)
        definitions = parse_ability_definitions(
            build_hero_mechanics(job.hero, job.context.normal_assets)
        )
    except (ArtifactError, MechanicsError, ValueError) as error:
        return str(error)
    invalid = _find_invalid_imbue_target(selected, definitions)
    if invalid:
        return invalid
    guide = build_purchase_guide_from_evidence(job.hero, selected)
    if not guide.has_complete_item_coverage:
        return "Beam guide lacks supported item coverage in every tier"
    return None
