from __future__ import annotations

import hashlib
import html
import json
import re
from collections import Counter
from typing import TYPE_CHECKING, Any

from .power_curve import summarize_duration_curve
from .purchase_guide import PurchaseGuide, format_purchase_window

if TYPE_CHECKING:
    from .api import HeroDurationStat, Patch
    from .ranks import RankRange

CONTEXT_SCHEMA_VERSION = 4
KIT_BASIS_SCHEMA_VERSION = 1
NARRATIVE_BASIS_SCHEMA_VERSION = 2
TIER_LABELS = {1: "I", 2: "II", 3: "III", 4: "IV"}


class StrategyContextError(ValueError):
    """Raised when an exported strategy context is malformed or was edited."""


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = re.sub(r"<br\s*/?>", " ", value, flags=re.IGNORECASE)
    text = re.sub(r"<svg\b.*?</svg>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\{[^}]+\}", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip() or None


def _description(asset: dict[str, Any]) -> dict[str, str]:
    raw = asset.get("description")
    if not isinstance(raw, dict):
        return {}
    return {
        str(key): text
        for key, value in raw.items()
        if (text := _clean_text(value)) is not None
    }


def _stat_properties(
    asset: dict[str, Any],
    *,
    include_all_labeled: bool = False,
) -> list[dict[str, Any]]:
    properties = asset.get("properties")
    if not isinstance(properties, dict):
        return []
    result = []
    for property_name, raw in properties.items():
        if not isinstance(raw, dict):
            continue
        value = raw.get("value")
        if value is None:
            continue
        if isinstance(value, (int, float)) and value == 0:
            continue
        if isinstance(value, str) and value in {"0", "0.0", ""}:
            continue
        label = _clean_text(raw.get("label") or raw.get("postvalue_label"))
        if (
            raw.get("tooltip_section") != "innate"
            and not raw.get("tooltip_is_important")
            and not (include_all_labeled and label)
        ):
            continue
        result.append({
            "property": str(property_name),
            "label": label or str(property_name),
            "value": value,
            "postfix": _clean_text(raw.get("postfix")),
        })
    return result


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _narrative_basis(context: dict[str, Any]) -> dict[str, Any]:
    ability_path = context.get("ability_path")
    duration_curve = context.get("duration_curve")
    tiers = context.get("tiers")
    return {
        "schema_version": NARRATIVE_BASIS_SCHEMA_VERSION,
        "hero_id": context.get("hero_id"),
        "hero": context.get("hero"),
        "hero_description": context.get("hero_description"),
        "abilities": context.get("abilities"),
        "ability_path": (
            {
                "selection": ability_path.get("selection"),
                "steps": ability_path.get("steps"),
            }
            if isinstance(ability_path, dict)
            else None
        ),
        "duration_curve": (
            {
                "shape": duration_curve.get("shape"),
                "strongest_phase": duration_curve.get("strongest_phase"),
                "weakest_phase": duration_curve.get("weakest_phase"),
            }
            if isinstance(duration_curve, dict)
            else None
        ),
        "tiers": {
            label: [
                {
                    "rank_by_pick_rate": item.get("rank_by_pick_rate"),
                    "item_id": item.get("item_id"),
                    "item": item.get("item"),
                    "slot": item.get("slot"),
                    "is_active_item": item.get("is_active_item"),
                    "description": item.get("description"),
                    "stats": item.get("stats"),
                    "purchase_windows": [
                        window.get("label")
                        for window in item.get("purchase_windows", [])
                        if isinstance(window, dict)
                    ],
                }
                for item in items
                if isinstance(item, dict)
            ]
            for label, items in (tiers.items() if isinstance(tiers, dict) else ())
            if isinstance(items, list)
        },
        "interpretation_constraints": context.get("interpretation_constraints"),
    }


def _kit_basis(context: dict[str, Any]) -> dict[str, Any]:
    ability_path = context.get("ability_path")
    return {
        "schema_version": KIT_BASIS_SCHEMA_VERSION,
        "hero_id": context.get("hero_id"),
        "hero": context.get("hero"),
        "hero_description": context.get("hero_description"),
        "abilities": context.get("abilities"),
        "ability_path": (
            {
                "selection": ability_path.get("selection"),
                "steps": ability_path.get("steps"),
            }
            if isinstance(ability_path, dict)
            else None
        ),
    }


def calculate_kit_basis_sha256(context: dict[str, Any]) -> str:
    """Return the ability-only tactical fingerprint for one hero context.

    Returns:
        A lowercase hexadecimal SHA-256 digest.

    """
    return _canonical_hash(_kit_basis(context))


def calculate_narrative_basis_sha256(context: dict[str, Any]) -> str:
    """Return the tactical-basis fingerprint for one hero context.

    Returns:
        A lowercase hexadecimal SHA-256 digest.

    """
    return _canonical_hash(_narrative_basis(context))


def calculate_context_sha256(context: dict[str, Any]) -> str:
    """Return the full fingerprint for one hero context.

    Returns:
        A lowercase hexadecimal SHA-256 digest.

    """
    payload = dict(context)
    payload.pop("context_sha256", None)
    return _canonical_hash(payload)


def calculate_source_context_sha256(document: dict[str, Any]) -> str:
    """Return the fingerprint for a complete exported context document.

    Returns:
        A lowercase hexadecimal SHA-256 digest.

    """
    payload = dict(document)
    payload.pop("source_context_sha256", None)
    return _canonical_hash(payload)


def validate_strategy_context_document(document: dict[str, Any]) -> None:
    """Verify the schema, hero fingerprints, and full export fingerprint.

    Raises:
        StrategyContextError: If the document is malformed or no longer matches
            the fingerprints written by ``export-context``.

    """
    if document.get("schema_version") != CONTEXT_SCHEMA_VERSION:
        raise StrategyContextError("unsupported strategy-context schema")
    heroes = document.get("heroes")
    if not isinstance(heroes, list):
        raise StrategyContextError("strategy context is missing its heroes array")

    seen_hero_ids: set[int] = set()
    for entry in heroes:
        if not isinstance(entry, dict) or not isinstance(entry.get("hero_id"), int):
            raise StrategyContextError("strategy context contains an invalid hero")
        hero_id = int(entry["hero_id"])
        if hero_id in seen_hero_ids:
            raise StrategyContextError(
                f"strategy context contains duplicate hero {hero_id}"
            )
        seen_hero_ids.add(hero_id)
        hero_name = str(entry.get("hero") or hero_id)
        if entry.get("kit_basis_sha256") != calculate_kit_basis_sha256(entry):
            raise StrategyContextError(
                f"strategy context kit basis was edited for {hero_name}; "
                "run export-context again"
            )
        if entry.get("narrative_basis_sha256") != calculate_narrative_basis_sha256(
            entry
        ):
            raise StrategyContextError(
                f"strategy context tactical basis was edited for {hero_name}; "
                "run export-context again"
            )
        if entry.get("context_sha256") != calculate_context_sha256(entry):
            raise StrategyContextError(
                f"strategy context was edited for {hero_name}; run export-context again"
            )

    if document.get("source_context_sha256") != calculate_source_context_sha256(
        document
    ):
        raise StrategyContextError(
            "strategy context document was edited; run export-context again"
        )


def _ability_assets(
    hero: dict[str, Any],
    assets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_class = {
        str(asset.get("class_name")): asset
        for asset in assets
        if asset.get("type") == "ability" and asset.get("class_name")
    }
    hero_items = hero.get("items")
    if not isinstance(hero_items, dict):
        hero_items = {}
    result = []
    for slot in range(1, 5):
        asset = by_class.get(str(hero_items.get(f"signature{slot}") or ""))
        if not asset or not isinstance(asset.get("id"), int):
            continue
        result.append({
            "ability_id": int(asset["id"]),
            "ability": str(asset.get("name") or f"Ability {slot}"),
            "slot": slot,
            "ability_type": str(asset.get("ability_type") or "signature").upper(),
            "description": _description(asset),
            "stats": _stat_properties(asset, include_all_labeled=True),
        })
    return result


def _ability_path(
    guide: PurchaseGuide,
    abilities_by_id: dict[int, dict[str, Any]],
) -> dict[str, Any] | None:
    path = guide.ability_path
    if path is None:
        return None
    purchases: Counter[int] = Counter()
    steps = []
    for index, ability_id in enumerate(path.ability_ids):
        prior = purchases[ability_id]
        ability = abilities_by_id.get(ability_id, {})
        steps.append({
            "position": index + 1,
            "quarter": index // 4 + 1,
            "ability_id": ability_id,
            "ability": str(ability.get("ability") or ability_id),
            "upgrade": "UNLOCK" if prior == 0 else f"T{prior}",
        })
        purchases[ability_id] += 1
    return {
        "selection": "MOST_PICKED_COMPLETE_PATH_THEN_RAW_WIN_RATE",
        "path_pick_rate": path.pick_rate,
        "raw_win_rate": path.win_rate,
        "matches": path.matches,
        "wins": path.wins,
        "losses": path.losses,
        "reliable_complete_path_matches": path.cohort_matches,
        "steps": steps,
    }


def build_hero_strategy_context(
    guide: PurchaseGuide,
    hero: dict[str, Any],
    assets: list[dict[str, Any]],
    duration_curve: tuple[HeroDurationStat, ...] = (),
    duration_distribution: dict[str, dict[str, float | int]] | None = None,
) -> dict[str, Any]:
    assets_by_id = {
        int(asset["id"]): asset for asset in assets if isinstance(asset.get("id"), int)
    }
    abilities = _ability_assets(hero, assets)
    abilities_by_id = {int(ability["ability_id"]): ability for ability in abilities}

    tiers: dict[str, list[dict[str, Any]]] = {}
    for tier in range(1, 5):
        tier_items = []
        for rank, item in enumerate(guide.tiers[tier], start=1):
            asset = assets_by_id.get(item.item_id, {})
            tier_items.append({
                "rank_by_pick_rate": rank,
                "item_id": item.item_id,
                "item": item.name,
                "slot": str(asset.get("item_slot_type") or "unknown").upper(),
                "is_active_item": bool(asset.get("is_active_item")),
                "description": _description(asset),
                "stats": _stat_properties(asset),
                "purchase_windows": [
                    {
                        "label": format_purchase_window(window),
                        "raw_win_rate": window.true_win_rate,
                        "matches": window.matches,
                    }
                    for window in item.windows
                ],
                "relative_pick_rate": item.relative_pick_rate,
                "raw_win_rate": item.overall_win_rate,
                "matches": item.overall_matches,
            })
        tiers[TIER_LABELS[tier]] = tier_items

    context = {
        "hero_id": guide.hero_id,
        "hero": guide.hero_name,
        "hero_description": _clean_text(hero.get("description")),
        "abilities": abilities,
        "ability_path": _ability_path(guide, abilities_by_id),
        "duration_curve": summarize_duration_curve(
            duration_curve,
            duration_distribution,
        ),
        "tiers": tiers,
        "interpretation_constraints": [
            "Each tier is a ranked menu of independent item options, not proof that every item was purchased together.",
            "The first three items in each tier are the core items to explain; later items are matchup alternatives.",
            "Treat tiers I–IV as four strategic quarters: establish, accelerate, pressure, and close.",
            "Use the duration curve to distinguish natural scaling from a build that compensates for a weak phase.",
            "An item restricted to charged or otherwise qualified abilities supports a trigger only when the selected ability's supplied properties show that qualification.",
            "Do not invent mechanics, numeric effects, combos, or matchups absent from this context.",
        ],
    }
    context["kit_basis_sha256"] = calculate_kit_basis_sha256(context)
    context["narrative_basis_sha256"] = calculate_narrative_basis_sha256(context)
    context["context_sha256"] = calculate_context_sha256(context)
    return context


def build_strategy_context_document(
    patch: Patch,
    contexts: list[dict[str, Any]],
    rank_range: RankRange,
) -> dict[str, Any]:
    document = {
        "schema_version": CONTEXT_SCHEMA_VERSION,
        "patch": {
            "title": patch.title,
            "published_at": patch.published_at,
            "start_timestamp": patch.start_timestamp,
        },
        "filters": {
            "game_mode": "STANDARD",
            "rank_range": rank_range.as_dict(),
            "minimum_complete_path_matches": 20,
        },
        "heroes": contexts,
    }
    document["source_context_sha256"] = calculate_source_context_sha256(document)
    return document
