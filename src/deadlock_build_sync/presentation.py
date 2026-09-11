from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from .beam_display import variant_statistics
from .guide_groups import describe_variants, validate_group_categories
from .purchase_categories import format_choice_instruction
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
MAX_BUILD_NAME_CHARACTERS = 50
MIN_BUILD_LABEL_CHARACTERS = 8
MIN_PATCH_LABEL_CHARACTERS = 4
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


def _format_as_of_date(timestamp: int) -> str:
    if timestamp <= 0:
        return "UNRESOLVED"
    return datetime.fromtimestamp(timestamp, UTC).date().isoformat()


def _format_compact_date(timestamp: int) -> str:
    if timestamp <= 0:
        return "????"
    return datetime.fromtimestamp(timestamp, UTC).strftime("%m%d")


def _format_statistics_window(start_timestamp: int, end_timestamp: int) -> str:
    start = _format_compact_date(start_timestamp)
    end = _format_compact_date(end_timestamp)
    return f"{start}–{end}"


def _format_build_name(
    persona: str,
    build_name: str,
    patch_title: str,
    stats_window: str,
) -> str:
    suffix = f" / {stats_window}"
    separator = " | "
    normalized_persona = " ".join(persona.split())
    if not normalized_persona:
        raise ValueError("persona must contain visible text")
    persona_budget = (
        MAX_BUILD_NAME_CHARACTERS
        - (2 * len(separator))
        - len(suffix)
        - MIN_BUILD_LABEL_CHARACTERS
        - MIN_PATCH_LABEL_CHARACTERS
    )
    persona_label = normalized_persona[:persona_budget].rstrip()
    prefix = f"{persona_label}{separator}"
    available = MAX_BUILD_NAME_CHARACTERS - len(prefix) - len(separator) - len(suffix)
    build_label = build_name.strip() or "Evidence Default"
    patch_label = patch_title.strip() or "Unknown Patch"
    patch_date = _PATCH_DATE.search(patch_label)
    if patch_date is not None:
        patch_label = f"{int(patch_date.group(1)):02}{int(patch_date.group(2)):02}"
    build_budget = min(
        len(build_label),
        max(
            MIN_BUILD_LABEL_CHARACTERS,
            available - min(len(patch_label), MIN_PATCH_LABEL_CHARACTERS),
        ),
    )
    patch_budget = available - build_budget
    return (
        f"{prefix}{build_label[:build_budget].rstrip()}{separator}"
        f"{patch_label[:patch_budget].rstrip()}{suffix}"
    )


def _describe_role_and_plan(guide: PurchaseGuide) -> tuple[str, str]:
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


def _describe_queue_rule(guide: PurchaseGuide) -> str:
    if any(category.compact for category in guide.rendered_categories):
        return "Queue follows CORE ITEMS only. All other panels are optional."
    if guide.purchase_guidance is not None:
        return "AUTO: CORE steps only. OPTIONAL, PICK ONE, UPGRADE, and ITEM POOL rows stay optional."
    if guide.optional_core_items:
        return "AUTO: CORE left→right. OPTIONAL CORE and TIER 1–4 never auto-queue."
    return "AUTO: CORE left→right. TIER 1–4 never auto-queue."


def _describe_ability_order(guide: PurchaseGuide) -> str | None:
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
    persona: str,
    patch_title: str,
    patch_published_at: str,
    rank_range: RankRange = DEFAULT_RANK_RANGE,
) -> BuildPresentation:
    """Create the complete Steam presentation for protobuf serialization.

    Returns:
        The validated player-facing presentation.

    Raises:
        ValueError: If required tags or a UTF-8 budget are invalid.

    """
    validate_group_categories(guide)
    queue = guide.match_mode.title() if guide.match_mode else "Unresolved"
    role_line, plan_line = _describe_role_and_plan(guide)
    lines = [
        role_line,
        _describe_queue_rule(guide),
        plan_line,
        (
            f"{queue} • {guide.rank_identity or rank_range.label} • data through "
            f"{_format_as_of_date(guide.as_of_timestamp)} • client "
            f"{guide.client_version or 'UNRESOLVED'}."
        ),
    ]
    if guide.evidence_summary:
        lines.extend([
            f"Evidence: {guide.evidence_summary['status']}. Timing: {guide.evidence_summary['timing_status']}.",
            f"Evidence limits: {guide.evidence_summary['limitations']}.",
        ])
    if statistics := variant_statistics(guide, detailed=True):
        lines.extend([
            "Default core: " + " ".join(statistics),
            "Rates describe validation matches with the complete core. Variant samples can overlap.",
            "Wealth states compare personal net worth with the lobby average. Behind: below 90%. Even: 90% through 110%. Ahead: above 110%.",
        ])
    if guide.variant_guides:
        lines.extend([
            f"{len(guide.variant_guides)} alternative variants. CORE ITEMS contains the complete default purchase path. V numbers identify the full variant paths below.",
            "ALTERNATIVE CORE contains common final items. Combine it with one panel marked ALTERNATIVE CORE +. Each complete variant replaces CORE ITEMS. Follow that variant's complete purchase order. Shared and variant items can occur at different steps."
            if any(
                category.name == "ALTERNATIVE CORE"
                for category in guide.rendered_categories
            )
            else "Each VARIANT panel contains its complete final core. Follow that variant's complete purchase order.",
            "Variant notes show recorded wealth states and complete-core win rates. State labels describe observed matches. They do not establish when to change a partly purchased core.",
        ])
        lines.extend(describe_variants(guide))
    if any(category.compact for category in guide.rendered_categories):
        lines.extend(_describe_purchase_details(guide))
    ability_summary = _describe_ability_order(guide)
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
        name=_format_build_name(
            persona,
            guide.build_archetype,
            patch_title,
            _format_statistics_window(
                guide.analysis_start_timestamp,
                guide.as_of_timestamp,
            ),
        ),
        tag_ids=(tag_ids[0], tag_ids[1], tag_ids[2]),
        description="\n".join(lines),
        categories=guide.rendered_categories,
        ability_path=guide.ability_path,
    )


def _describe_purchase_details(guide: PurchaseGuide) -> list[str]:
    guidance = guide.purchase_guidance
    if guidance is None:
        return []
    return [
        "Buy CORE ITEMS from left to right. All other sections are optional. Tier numbers show item prices. Keep the selected variant's core and pool together.",
        *(
            f"{step.name}: +{step.incremental_cost:,} souls; total {step.cumulative_cost:,}."
            for step in guidance.default_path.actions
        ),
        *(
            f"{card.name}: {format_choice_instruction(guidance, card)}"
            for card in guidance.choices
        ),
        *(
            f"{alternative.when} {alternative.swap}. {alternative.why} {alternative.skip}"
            for alternative in guide.core_alternatives
        ),
    ]
