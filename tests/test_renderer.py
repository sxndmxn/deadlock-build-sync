from dataclasses import replace
from typing import Any

import pytest

from deadlock_build_sync.mechanics import ItemGraph
from deadlock_build_sync.policy import (
    Branch,
    BuildPolicy,
    ClaimClass,
    EvidenceClaim,
    Guard,
    GuardOperator,
    NodeKind,
    PolicyError,
    PolicyNode,
    ValidationContext,
)
from deadlock_build_sync.presentation import build_presentation
from deadlock_build_sync.protobuf import ProtoField, encode_hero_build, parse_fields
from deadlock_build_sync.purchase_guide import PurchaseGuide
from deadlock_build_sync.renderer import (
    ProjectionIdentity,
    project_policy_to_guide,
    projection_fingerprint,
    validate_optional_annotation,
)
from deadlock_build_sync.snapshot import EvidenceUnit

SNAPSHOT = "b" * 64


def assets() -> list[dict[str, Any]]:
    return [
        {
            "id": item_id,
            "class_name": f"item_{item_id}",
            "name": f"Item {item_id}",
            "cost": item_id * 500,
            "component_items": [],
            "item_slot_type": "spirit",
            "item_tier": item_id,
            "shopable": True,
            "disabled": False,
        }
        for item_id in (1, 2)
    ]


def evidence(claim_id: str) -> EvidenceClaim:
    return EvidenceClaim(
        claim_id,
        ClaimClass.DESCRIPTIVE,
        SNAPSHOT,
        {"match_mode": "ranked"},
        EvidenceUnit.ELIGIBLE_APPEARANCE,
        100,
        (f"asset/{claim_id}",),
        frozenset({"observed"}),
        60,
        100,
        0.6,
        (0.5, 0.69),
        0.5,
    )


def policy(annotation: str | None = None) -> BuildPolicy:
    return BuildPolicy(
        1,
        12,
        "control",
        "kit/12",
        "protect allies",
        SNAPSHOT,
        "core",
        (
            PolicyNode(
                "core",
                NodeKind.PURCHASE,
                next_id="choice",
                evidence_ref="core-evidence",
                item_id=1,
            ),
            PolicyNode(
                "choice",
                NodeKind.OBJECTIVE_GATE,
                branches=(
                    Branch(
                        "counter",
                        Guard(
                            "enemy.threats",
                            GuardOperator.CONTAINS,
                            "hard_control",
                        ),
                    ),
                    Branch("end"),
                ),
                unlocks_flex_slots=1,
            ),
            PolicyNode(
                "counter",
                NodeKind.PURCHASE,
                next_id="sell-core",
                evidence_ref="counter-evidence",
                item_id=2,
                optional=True,
                required_flex_slots=1,
                imbue_target_ability_id=None,
                annotation=(
                    annotation
                    or "If hard control appears, choose this over core; activate before engaging; skip if control is absent."
                ),
            ),
            PolicyNode(
                "sell-core",
                NodeKind.SELL,
                next_id="end",
                evidence_ref="core-evidence",
                item_id=1,
            ),
            PolicyNode("end", NodeKind.END),
        ),
        (evidence("core-evidence"), evidence("counter-evidence")),
    )


def projected_guide(annotation: str | None = None) -> PurchaseGuide:
    item_assets = assets()
    return project_policy_to_guide(
        policy(annotation),
        ValidationContext(ItemGraph.from_assets(item_assets), {}, []),
        assets=item_assets,
        identity=ProjectionIdentity(
            "Kelvin",
            "hero_kelvin",
            12345,
            "ranked",
            "Phantom I [91]–Eternus VI [116]",
        ),
    )


def _build_details(guide: PurchaseGuide) -> list[ProtoField]:
    build = encode_hero_build(
        build_presentation(
            replace(
                guide,
                build_tag_ids=(1, 2, 3),
                build_archetype="Spirit Damage",
                as_of_timestamp=1_767_225_600,
            ),
            patch_title="Patch",
            patch_published_at="2026-08-08T00:00:00Z",
        ),
        build_id=2,
        account_id=3,
        timestamp=4,
    )
    details = next(
        field.value
        for field in parse_fields(build)
        if field.number == 10 and isinstance(field.value, bytes)
    )
    return list(parse_fields(details))


def test_projection_separates_default_queue_from_optional_branch() -> None:
    guide = projected_guide()

    assert [category.optional for category in guide.categories] == [False, True]
    assert [item.item_id for item in guide.categories[0].items] == [1]
    assert [item.item_id for item in guide.categories[1].items] == [2]
    assert guide.categories[0].items[0].sell_priority == 1
    assert guide.categories[1].items[0].required_flex_slots == 1
    assert guide.snapshot_id == SNAPSHOT
    assert guide.policy_id == policy().policy_id
    assert len(projection_fingerprint(guide)) == 64


def test_protobuf_preserves_optional_sell_flex_and_omission_semantics() -> None:
    categories = [
        field.value
        for field in _build_details(projected_guide())
        if field.number == 1 and isinstance(field.value, bytes)
    ]
    core_fields = {field.number: field.value for field in parse_fields(categories[0])}
    optional_fields = {
        field.number: field.value for field in parse_fields(categories[1])
    }
    assert core_fields[6] == 0
    assert optional_fields[6] == 1

    core_mod = next(
        field.value
        for field in parse_fields(categories[0])
        if field.number == 1 and isinstance(field.value, bytes)
    )
    optional_mod = next(
        field.value
        for field in parse_fields(categories[1])
        if field.number == 1 and isinstance(field.value, bytes)
    )
    core_mod_fields = {field.number: field.value for field in parse_fields(core_mod)}
    optional_mod_fields = {
        field.number: field.value for field in parse_fields(optional_mod)
    }
    assert core_mod_fields[4] == 1
    assert 3 not in core_mod_fields
    assert 5 not in core_mod_fields
    assert optional_mod_fields[3] == 1


def test_description_identifies_snapshot_policy_client_mode_rank_and_claim_limit() -> (
    None
):
    build = encode_hero_build(
        build_presentation(
            replace(
                projected_guide(),
                build_tag_ids=(1, 2, 3),
                build_archetype="Spirit Damage",
                as_of_timestamp=1_767_225_600,
            ),
            patch_title="Patch",
            patch_published_at="2026-08-08T00:00:00Z",
        ),
        build_id=2,
        account_id=3,
        timestamp=4,
    )
    description = next(
        field.value.decode()
        for field in parse_fields(build)
        if field.number == 6 and isinstance(field.value, bytes)
    )

    assert f"Snapshot: {SNAPSHOT}." in description
    assert "client 12345." in description
    assert "Ranked" in description
    assert "Phantom I [91]–Eternus VI [116]" in description
    assert "no causal item effect" in description


@pytest.mark.parametrize(
    "annotation",
    [
        "Choose this item.",
        "If control appears, choose this over core and activate before engaging.",
        "If control appears, choose this over core; skip if absent.",
        "x" * 241,
    ],
)
def test_optional_annotations_fail_closed(annotation: str) -> None:
    with pytest.raises(PolicyError, match="optional annotation"):
        validate_optional_annotation(annotation)
