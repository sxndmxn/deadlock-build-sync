from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .ability_order import MIN_ABILITY_PATH_MATCHES, select_ability_path
from .narratives import NarrativeCatalog, apply_narrative
from .power_curve import summarize_duration_distribution
from .purchase_guide import PurchaseGuide, build_purchase_guide
from .strategy_context import build_hero_strategy_context

if TYPE_CHECKING:
    from .api import DeadlockApi, HeroDurationStat, Patch
    from .ranks import RankRange


class GuideError(RuntimeError):
    """Raised when analytics cannot produce a usable guide."""


@dataclass(frozen=True)
class GeneratedGuides:
    guides: list[PurchaseGuide]
    contexts: list[dict[str, Any]]
    skipped_heroes: tuple[str, ...]
    rank_range: RankRange
    persona: str
    patch: Patch


def _handle_incomplete_analytics(
    *,
    all_heroes: bool,
    skipped_heroes: list[str],
    hero_name: str,
    reason: str,
) -> None:
    if all_heroes:
        skipped_heroes.append(f"{hero_name} ({reason})")
        return
    raise GuideError(f"{hero_name} did not have {reason}")


def _duration_distribution(
    heroes: list[dict[str, Any]],
    curves: dict[int, tuple[HeroDurationStat, ...]],
) -> dict[str, dict[str, float | int]]:
    active_hero_ids = {int(hero["id"]) for hero in heroes}
    return summarize_duration_distribution({
        hero_id: points
        for hero_id, points in curves.items()
        if hero_id in active_hero_ids
    })


def select_heroes(
    heroes: list[dict[str, Any]],
    *,
    hero_query: str | None,
    all_heroes: bool,
) -> list[dict[str, Any]]:
    if all_heroes:
        return heroes
    if not hero_query:
        raise GuideError("pass --hero NAME or --all")
    normalized = hero_query.casefold().replace(" ", "").replace("&", "and")
    matches = []
    for hero in heroes:
        candidates = {
            str(hero.get("id") or ""),
            str(hero.get("name") or "").casefold().replace(" ", "").replace("&", "and"),
            str(hero.get("class_name") or "").casefold().removeprefix("hero_"),
        }
        if normalized in candidates:
            matches.append(hero)
    if not matches:
        raise GuideError(f"active hero not found: {hero_query}")
    if len(matches) > 1:
        names = ", ".join(str(hero.get("name")) for hero in matches)
        raise GuideError(f"hero query is ambiguous: {names}")
    return matches


def generate_guides(
    api: DeadlockApi,
    *,
    account_id: int,
    hero_query: str | None,
    all_heroes: bool,
    narrative_catalog: NarrativeCatalog | None = None,
) -> GeneratedGuides:
    heroes = api.active_heroes()
    selected = select_heroes(heroes, hero_query=hero_query, all_heroes=all_heroes)
    assets = api.items()
    patch = api.current_patch()
    duration_curves = api.hero_stats_by_duration(
        min_unix_timestamp=patch.start_timestamp,
    )
    duration_distribution = _duration_distribution(heroes, duration_curves)

    guides: list[PurchaseGuide] = []
    contexts: list[dict[str, Any]] = []
    skipped_heroes: list[str] = []
    for hero in selected:
        overall = api.item_stats(
            hero_id=int(hero["id"]),
            min_unix_timestamp=patch.start_timestamp,
            min_matches=10,
        )
        buckets = api.item_stats(
            hero_id=int(hero["id"]),
            min_unix_timestamp=patch.start_timestamp,
            min_matches=2,
            bucket="net_worth_by_1000",
        )
        ability_rows = api.ability_order_stats(
            hero_id=int(hero["id"]),
            min_unix_timestamp=patch.start_timestamp,
            min_matches=MIN_ABILITY_PATH_MATCHES,
        )
        guide = build_purchase_guide(
            hero,
            assets,
            overall,
            buckets,
            ability_path=select_ability_path(ability_rows),
        )
        if not guide.has_complete_item_coverage:
            _handle_incomplete_analytics(
                all_heroes=all_heroes,
                skipped_heroes=skipped_heroes,
                hero_name=guide.hero_name,
                reason="eight reliable items in every tier",
            )
            continue
        if guide.ability_path is None:
            _handle_incomplete_analytics(
                all_heroes=all_heroes,
                skipped_heroes=skipped_heroes,
                hero_name=guide.hero_name,
                reason="a reliable complete 16-step ability path",
            )
            continue
        context = build_hero_strategy_context(
            guide,
            hero,
            assets,
            duration_curves.get(int(hero["id"]), ()),
            duration_distribution,
        )
        abilities = context.get("abilities")
        if not isinstance(abilities, list) or len(abilities) != 4:
            _handle_incomplete_analytics(
                all_heroes=all_heroes,
                skipped_heroes=skipped_heroes,
                hero_name=guide.hero_name,
                reason="all four ability assets",
            )
            continue
        if context.get("duration_curve") is None:
            _handle_incomplete_analytics(
                all_heroes=all_heroes,
                skipped_heroes=skipped_heroes,
                hero_name=guide.hero_name,
                reason="a complete reliable duration curve",
            )
            continue
        if narrative_catalog is not None:
            guide = apply_narrative(guide, context, patch, narrative_catalog)
        guides.append(guide)
        contexts.append(context)
    return GeneratedGuides(
        guides=guides,
        contexts=contexts,
        skipped_heroes=tuple(skipped_heroes),
        rank_range=api.rank_range,
        persona=api.steam_persona(account_id),
        patch=patch,
    )
