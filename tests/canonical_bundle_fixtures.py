"""Build real purchase projections for installation contract tests."""

from pathlib import Path

from deadlock_build_sync.build_evidence import load_build_evidence, select_hero_build
from deadlock_build_sync.mechanics import ItemGraph, ability_definitions_from_kit
from deadlock_build_sync.policy import BuildPolicy, ValidationContext
from deadlock_build_sync.purchase_categories import category_records
from deadlock_build_sync.purchase_guidance import attach_purchase_guidance
from deadlock_build_sync.purchase_guide import build_purchase_guide_from_evidence
from deadlock_build_sync.renderer import ProjectionIdentity, project_policy_to_guide


def fixture_kit() -> dict[str, object]:
    return {
        "class_name": "hero_kelvin",
        "abilities": [{"id": item} for item in (10, 20, 30, 40)],
        "level_info": {
            str(level): {"ability_unlocks": 1, "ability_points": 5}
            for level in range(1, 17)
        },
    }


def canonical_projection(
    path: Path, policy: BuildPolicy
) -> tuple[list[dict[str, object]], int, dict[str, object]]:
    catalog = load_build_evidence(path)
    assets = list(catalog.assets)
    kit = fixture_kit()
    layout = build_purchase_guide_from_evidence(
        {"id": 12, "name": "Kelvin", "class_name": "hero_kelvin"},
        select_hero_build(catalog.heroes[12], assets),
    )
    guide = project_policy_to_guide(
        policy,
        ValidationContext(
            ItemGraph.from_assets(assets),
            ability_definitions_from_kit(kit),
            kit["level_info"],
        ),
        assets=assets,
        identity=ProjectionIdentity("Kelvin", "hero_kelvin", 123, "ranked", "fixture"),
        layout_source=layout,
    )
    guide = attach_purchase_guidance(guide, assets)
    assert guide.purchase_guidance is not None
    return (
        category_records(guide.rendered_categories),
        guide.core_target_cost,
        guide.purchase_guidance.as_dict(),
    )
