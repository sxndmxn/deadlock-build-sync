"""Render the Steam presentation for review without access to Steam data."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .purchase_categories import serialize_category_records

if TYPE_CHECKING:
    from .presentation import BuildPresentation
    from .purchase_types import GuideCategory


def serialize_presentation(presentation: BuildPresentation) -> dict[str, object]:
    """Return the content that Steam serialization receives.

    Returns:
        The complete presentation record, without installation identity fields.

    """
    ability = presentation.ability_path
    return {
        "schema_version": 1,
        "hero_id": presentation.hero_id,
        "name": presentation.name,
        "description": presentation.description,
        "tag_ids": list(presentation.tag_ids),
        "categories": serialize_category_records(presentation.categories),
        "ability_order": list(ability.ability_ids) if ability else [],
        "ability_annotation": ability.annotation if ability else None,
    }


def render_presentation_markdown(presentation: BuildPresentation) -> str:
    """Render every panel, item note, and description in the Steam presentation.

    Returns:
        Markdown with the complete ordered presentation.

    """
    lines = [
        f"# {presentation.name}",
        "",
        "Steam build content. Panels and items follow serialization order.",
        "The client controls panel placement. Dimensions use native layout units.",
        f"Hero ID: {presentation.hero_id}. Tags: {', '.join(map(str, presentation.tag_ids))}.",
        "",
    ]
    for category in presentation.categories:
        lines.extend(_render_category_markdown(category))
    lines.extend(["## Ability order", ""])
    if ability := presentation.ability_path:
        lines.extend([
            " → ".join(map(str, ability.ability_ids)),
            "",
            "First ability note:",
            "",
            *(
                f"    {line}" if line else ""
                for line in ability.annotation.splitlines()
            ),
            "",
        ])
    else:
        lines.extend(["No ability order.", ""])
    lines.extend([
        "## Build description",
        "",
        *(
            f"    {line}" if line else ""
            for line in presentation.description.splitlines()
        ),
        "",
    ])
    return "\n".join(lines)


def _render_category_markdown(category: GuideCategory) -> list[str]:
    lines = [
        f"## {category.name}",
        "",
        f"Optional: {'yes' if category.optional else 'no'}. Size: {category.width:g} x {category.height:g}.",
        "",
    ]
    if category.description:
        lines.extend([
            *(
                f"    {line}" if line else ""
                for line in category.description.splitlines()
            ),
            "",
        ])
    if not category.items:
        lines.extend(["No items.", ""])
    for index, item in enumerate(category.items, 1):
        lines.extend([
            f"{index}. **{item.name}** (ID {item.item_id})",
            "",
            *(
                f"        {line}" if line else ""
                for line in item.annotation.splitlines()
            ),
            "",
        ])
        for label, value in (
            ("Required flex slots", item.required_flex_slots),
            ("Sell priority", item.sell_priority),
            ("Imbue ability ID", item.imbue_target_ability_id),
        ):
            if value is not None:
                lines.extend([f"    {label}: {value}.", ""])
    return lines
