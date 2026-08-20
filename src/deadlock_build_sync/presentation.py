from __future__ import annotations

import re
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

LEGACY_MANAGED_MARKER = "[deadlock-build-sync:v1]"
MANAGED_MARKER = "[deadlock-build-sync:v2]"
AUTHOR_PREFIX = "XMLJDX"
MAX_BUILD_NAME_CHARACTERS = 50
_PATCH_DATE = re.compile(r"(?<!\d)(\d{1,2})-(\d{1,2})-\d{4}(?!\d)")


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


def _as_of_date(timestamp: int) -> str:
    if timestamp <= 0:
        return "UNRESOLVED"
    return datetime.fromtimestamp(timestamp, UTC).date().isoformat()


def _compact_date(timestamp: int) -> str:
    if timestamp <= 0:
        return "????"
    return datetime.fromtimestamp(timestamp, UTC).strftime("%m%d")


def _stats_window(start_timestamp: int, end_timestamp: int) -> str:
    start = _compact_date(start_timestamp)
    end = _compact_date(end_timestamp)
    return f"{start}–{end}"


def _build_name(
    build_name: str,
    patch_title: str,
    stats_window: str,
) -> str:
    prefix = f"{AUTHOR_PREFIX} | "
    suffix = f" / {stats_window}"
    separator = " | "
    available = MAX_BUILD_NAME_CHARACTERS - len(prefix) - len(separator) - len(suffix)
    build_label = build_name.strip() or "Evidence Default"
    patch_label = patch_title.strip() or "Unknown Patch"
    patch_date = _PATCH_DATE.search(patch_label)
    if patch_date is not None:
        patch_label = f"{int(patch_date.group(1)):02}{int(patch_date.group(2)):02}"
    build_budget = min(len(build_label), max(8, available - min(len(patch_label), 4)))
    patch_budget = available - build_budget
    return (
        f"{prefix}{build_label[:build_budget].rstrip()}{separator}"
        f"{patch_label[:patch_budget].rstrip()}{suffix}"
    )


def _role_and_plan(guide: PurchaseGuide) -> tuple[str, str]:
    profile = guide.tactical_profile
    if profile is not None:
        return (
            f"{profile.primary_role}: {profile.fight_role}",
            profile.economy_plan,
        )
    return (
        guide.summary or f"Evidence-grounded default for {guide.hero_name}.",
        "Use observed order as a default and deviate when the match requires.",
    )


def _queue_rule(guide: PurchaseGuide) -> str:
    if guide.optional_core_items:
        return "AUTO: CORE left→right. OPTIONAL CORE and TIER 1–4 never auto-queue."
    return "AUTO: CORE left→right. TIER 1–4 never auto-queue."


def _ability_summary(guide: PurchaseGuide) -> str | None:
    ability_path = guide.ability_path
    if ability_path is None:
        return None
    if ability_path.filter_item_ids:
        scope = "item-filtered observed"
    elif guide.path_id != "default":
        scope = "shared hero-wide observed"
    else:
        scope = "state-composed observed"
    return f"Ability order: {scope} default • tail support n={ability_path.matches:,}."


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
    role_line, plan_line = _role_and_plan(guide)
    lines = [
        role_line,
        _queue_rule(guide),
        plan_line,
        (
            f"{queue} • {guide.rank_identity or rank_range.label} • data through "
            f"{_as_of_date(guide.as_of_timestamp)} • client "
            f"{guide.client_version or 'UNRESOLVED'}."
        ),
    ]
    ability_summary = _ability_summary(guide)
    if ability_summary is not None:
        lines.append(ability_summary)
    lines.extend([
        "",
        MANAGED_MARKER,
        f"Build path: {guide.path_id}.",
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
            (guide.path_label if guide.path_id != "default" else guide.build_archetype),
            patch_title,
            _stats_window(
                guide.analysis_start_timestamp,
                guide.as_of_timestamp,
            ),
        ),
        tag_ids=(tag_ids[0], tag_ids[1], tag_ids[2]),
        description="\n".join(lines),
        categories=guide.rendered_categories,
        ability_path=guide.ability_path,
    )
