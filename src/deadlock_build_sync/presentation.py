from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from .purchase_guide import (
    MAX_CATEGORY_DESCRIPTION_BYTES,
    MAX_ITEM_ANNOTATION_BYTES,
    GuideCategory,
    PurchaseGuide,
)
from .ranks import DEFAULT_RANK_RANGE, RankRange

if TYPE_CHECKING:
    from .ability_order import AbilityPath

MANAGED_MARKER = "[deadlock-build-sync:v1]"
MAX_BUILD_NAME_CHARACTERS = 50


@dataclass(frozen=True)
class BuildPresentation:
    hero_id: int
    name: str
    tag_ids: tuple[int, int, int]
    description: str
    categories: tuple[GuideCategory, ...]
    ability_path: AbilityPath | None

    def __post_init__(self) -> None:
        """Reject values that the Steam presentation contract cannot represent.

        Raises:
            ValueError: If a title, tag, marker, or UTF-8 budget is invalid.

        """
        if not self.name or len(self.name) > MAX_BUILD_NAME_CHARACTERS:
            raise ValueError("build name must contain 1–50 characters")
        if len(self.tag_ids) != 3 or any(tag_id <= 0 for tag_id in self.tag_ids):
            raise ValueError("build presentation requires exactly three nonzero tags")
        if len(set(self.tag_ids)) != 3:
            raise ValueError("build presentation tags must be distinct")
        if MANAGED_MARKER not in self.description:
            raise ValueError("build description is missing the managed marker")
        for category in self.categories:
            if (
                len(category.description.encode("utf-8"))
                > MAX_CATEGORY_DESCRIPTION_BYTES
            ):
                raise ValueError(
                    f"category {category.name} description exceeds the UTF-8 limit"
                )
            for item in category.items:
                if len(item.annotation.encode("utf-8")) > MAX_ITEM_ANNOTATION_BYTES:
                    raise ValueError(
                        f"item {item.item_id} annotation exceeds the UTF-8 limit"
                    )


def _date(value: str) -> str:
    try:
        return datetime.fromisoformat(value).date().isoformat()
    except ValueError:
        return "UNKNOWN"


def _as_of_date(timestamp: int) -> str:
    if timestamp <= 0:
        return "UNRESOLVED"
    return datetime.fromtimestamp(timestamp, UTC).date().isoformat()


def _build_name(archetype: str, queue: str, epoch_date: str) -> str:
    suffix = f" | {queue} | {epoch_date}"
    available = MAX_BUILD_NAME_CHARACTERS - len(suffix)
    label = (archetype.strip() or "Evidence Default")[: max(1, available)]
    return f"{label}{suffix}"


def build_presentation(
    guide: PurchaseGuide,
    *,
    patch_title: str,
    patch_published_at: str,
    rank_range: RankRange = DEFAULT_RANK_RANGE,
) -> BuildPresentation:
    """Create a complete player-first value for pure protobuf serialization.

    Returns:
        The validated player-facing presentation.

    Raises:
        ValueError: If required tags or a UTF-8 budget are invalid.

    """
    queue = guide.match_mode.title() if guide.match_mode else "Unresolved"
    profile = guide.tactical_profile
    if profile is not None:
        role_line = f"{profile.primary_role}: {profile.fight_role}"
        plan_line = profile.economy_plan
    else:
        role_line = guide.summary or f"Evidence-grounded default for {guide.hero_name}."
        plan_line = (
            "Use observed order as a default and deviate when the match requires."
        )
    lines = [
        role_line,
        "AUTO: CORE left→right. TIER 1–4 are optional and never auto-queued.",
        plan_line,
        (
            f"{queue} • {guide.rank_identity or rank_range.label} • data through "
            f"{_as_of_date(guide.as_of_timestamp)} • client "
            f"{guide.client_version or 'UNRESOLVED'}."
        ),
    ]
    if guide.ability_path is not None:
        lines.append(
            "Ability order: state-composed observed default • tail support "
            f"n={guide.ability_path.matches:,}."
        )
    lines.extend([
        "",
        MANAGED_MARKER,
        "Private evidence-grounded guide generated from deadlock-api.com.",
        f"Patch: {patch_title} ({patch_published_at}).",
        f"Snapshot: {guide.snapshot_id or 'UNRESOLVED'}.",
        f"Policy: {guide.policy_id or 'UNRESOLVED'}.",
        "Claim limit: observational; no causal item effect.",
    ])
    tag_ids = tuple(guide.build_tag_ids)
    if len(tag_ids) != 3:
        raise ValueError("guide does not have exactly three build tags")
    return BuildPresentation(
        hero_id=guide.hero_id,
        name=_build_name(
            guide.build_archetype,
            queue,
            _date(patch_published_at),
        ),
        tag_ids=(tag_ids[0], tag_ids[1], tag_ids[2]),
        description="\n".join(lines),
        categories=guide.rendered_categories,
        ability_path=guide.ability_path,
    )
