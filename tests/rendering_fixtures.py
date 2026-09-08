"""Decode rendered build details for output assertions."""

from dataclasses import replace

from deadlock_build_sync.presentation import build_presentation
from deadlock_build_sync.protobuf import ProtoField, encode_hero_build, parse_fields
from deadlock_build_sync.purchase_guide import PurchaseGuide


def build_details(guide: PurchaseGuide) -> list[ProtoField]:
    build = encode_hero_build(
        build_presentation(
            replace(
                guide,
                build_tag_ids=(1, 2, 3),
                build_archetype="Spirit Damage",
                as_of_timestamp=1_767_225_600,
            ),
            persona="Player",
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
