"""Validated input and output values for live recommendations."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import TYPE_CHECKING

from .match_choices import MatchEconomy

if TYPE_CHECKING:
    from pathlib import Path

DECISION_STATE_SCHEMA_VERSION = 3
_DECISION_STATE_FIELDS = frozenset({
    "schema_version",
    "path_id",
    "selected_optional_items",
    "placement_overrides",
    "core_substitution_item_id",
    "economy",
    "enemy_observed_at_s",
    "build_evidence_id",
    "client_version",
    "patch_identity",
    "match_mode",
    "game_mode",
    "hero_id",
    "clock_s",
    "average_badge",
    "liquid_souls",
    "purchases",
    "inventory",
    "learned_abilities",
    "enemy_hero_ids",
    "lane_enemy_hero_ids",
    "enemy_item_ids",
    "allied_hero_ids",
    "objectives",
    "threats",
})
_INVENTORY_FIELDS = frozenset({
    "items",
    "components",
    "open_slots",
    "flex_slots",
    "active_bindings",
})


class RecommendationError(ValueError):
    """Raised when decision state or recommendation evidence is invalid."""


class RecommendationAction(StrEnum):
    BUY = "buy"
    SAVE = "save"
    END = "end"
    ABSTAIN = "abstain"


@dataclass(frozen=True)
class DecisionState:
    build_evidence_id: str
    client_version: int
    patch_identity: str
    match_mode: str
    game_mode: str
    hero_id: int
    clock_s: int
    average_badge: int
    liquid_souls: int
    purchases: tuple[int, ...]
    owned_items: tuple[int, ...]
    owned_components: tuple[int, ...]
    open_slots: int
    unlocked_flex_slots: int
    active_bindings: int
    learned_abilities: tuple[int, ...]
    enemy_hero_ids: tuple[int, ...] = ()
    lane_enemy_hero_ids: tuple[int, ...] = ()
    enemy_item_ids: tuple[int, ...] = ()
    allied_hero_ids: tuple[int, ...] = ()
    objectives: tuple[str, ...] = ()
    threats: tuple[str, ...] = ()
    path_id: str | None = None
    selected_optional_items: tuple[int, ...] = ()
    placement_overrides: dict[int, int] = field(default_factory=dict)
    core_substitution_item_id: int | None = None
    economy: MatchEconomy | None = None
    enemy_observed_at_s: int | None = None

    @classmethod
    def from_file(cls, path: Path) -> DecisionState:
        """Load and validate a deidentified decision-state JSON document.

        Returns:
            The closed recommendation state.

        Raises:
            RecommendationError: If the document is missing or malformed.

        """
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RecommendationError(
                f"could not read decision state {path}: {error}"
            ) from error
        return cls.from_document(value)

    @classmethod
    def from_document(cls, value: object) -> DecisionState:
        """Validate the same closed state used by recommend and offline replay.

        Returns:
            A validated decision state.

        Raises:
            RecommendationError: If any state field is malformed.

        """
        if not isinstance(value, dict):
            raise RecommendationError("decision state root must be an object")
        if value.get("schema_version") != DECISION_STATE_SCHEMA_VERSION:
            raise RecommendationError("unsupported decision-state schema")
        unknown = set(value) - _DECISION_STATE_FIELDS
        if unknown:
            raise RecommendationError(
                "decision state contains unsupported fields: "
                + ", ".join(sorted(str(field) for field in unknown))
            )
        inventory = value.get("inventory")
        if not isinstance(inventory, dict):
            raise RecommendationError("decision state has no inventory")
        unknown_inventory = set(inventory) - _INVENTORY_FIELDS
        if unknown_inventory:
            raise RecommendationError(
                "decision state inventory contains unsupported fields: "
                + ", ".join(sorted(str(field) for field in unknown_inventory))
            )
        if "lane_enemy_hero_ids" not in value:
            raise RecommendationError("decision state lacks lane enemy heroes")
        state = cls(
            build_evidence_id=_require_state_text(
                value.get("build_evidence_id"), "build evidence id"
            ),
            client_version=_require_state_integer(
                value.get("client_version"), "client version", minimum=1
            ),
            patch_identity=_require_state_text(
                value.get("patch_identity"), "patch identity"
            ),
            match_mode=_require_state_text(value.get("match_mode"), "match mode"),
            game_mode=_require_state_text(value.get("game_mode"), "game mode"),
            hero_id=_require_state_integer(value.get("hero_id"), "hero id", minimum=1),
            clock_s=_require_state_integer(value.get("clock_s"), "clock", minimum=0),
            average_badge=_require_state_integer(
                value.get("average_badge"), "average badge", minimum=1
            ),
            liquid_souls=_require_state_integer(
                value.get("liquid_souls"), "liquid souls", minimum=0
            ),
            purchases=_parse_state_integers(value.get("purchases"), "purchase history"),
            owned_items=_parse_unique_state_integers(
                inventory.get("items"), "owned items"
            ),
            owned_components=_parse_unique_state_integers(
                inventory.get("components"), "owned components"
            ),
            open_slots=_require_state_integer(
                inventory.get("open_slots"), "open slots", minimum=0
            ),
            unlocked_flex_slots=_require_state_integer(
                inventory.get("flex_slots"), "flex slots", minimum=0
            ),
            active_bindings=_require_state_integer(
                inventory.get("active_bindings"), "active bindings", minimum=0
            ),
            learned_abilities=_parse_unique_state_integers(
                value.get("learned_abilities"), "learned abilities"
            ),
            enemy_hero_ids=_parse_unique_state_integers(
                value.get("enemy_hero_ids", []), "enemy heroes"
            ),
            lane_enemy_hero_ids=_parse_unique_state_integers(
                value.get("lane_enemy_hero_ids", []), "lane enemy heroes"
            ),
            enemy_item_ids=_parse_unique_state_integers(
                value.get("enemy_item_ids", []), "enemy items"
            ),
            allied_hero_ids=_parse_unique_state_integers(
                value.get("allied_hero_ids", []), "allied heroes"
            ),
            objectives=_parse_unique_state_strings(
                value.get("objectives", []), "objectives"
            ),
            threats=_parse_unique_state_strings(value.get("threats", []), "threats"),
        )
        state = replace(
            state,
            path_id=_require_state_text(value.get("path_id"), "path id")
            if value.get("path_id") is not None
            else None,
            selected_optional_items=_parse_unique_state_integers(
                value.get("selected_optional_items", []), "selected optional items"
            ),
            placement_overrides=_parse_purchase_placements(
                value.get("placement_overrides", {})
            ),
            core_substitution_item_id=_parse_optional_state_integer(
                value.get("core_substitution_item_id"), "core substitution item"
            ),
            economy=_parse_match_economy(value.get("economy")),
            enemy_observed_at_s=_require_state_integer(
                value.get("enemy_observed_at_s"), "enemy observation time", minimum=0
            )
            if value.get("enemy_observed_at_s") is not None
            else None,
        )
        if not set(state.placement_overrides) <= set(state.selected_optional_items):
            raise RecommendationError(
                "Placement overrides must refer to selected optional items"
            )
        if not set(state.lane_enemy_hero_ids) <= set(state.enemy_hero_ids):
            raise RecommendationError("lane enemy heroes are not on the enemy team")
        return state


@dataclass(frozen=True)
class Recommendation:
    action: RecommendationAction
    hero_id: int
    policy_id: str
    item_id: int | None = None
    target_item_id: int | None = None
    incremental_cost: int | None = None
    support: int | None = None
    support_share: float | None = None
    backoff_level: str | None = None
    reason: str = ""
    counter: dict[str, object] | None = None
    purchase_plan: dict[str, object] | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "action": self.action.value,
            "hero_id": self.hero_id,
            "policy_id": self.policy_id,
            "item_id": self.item_id,
            "target_item_id": self.target_item_id,
            "incremental_cost": self.incremental_cost,
            "support": self.support,
            "support_share": self.support_share,
            "backoff_level": self.backoff_level,
            "reason": self.reason,
            "counter": self.counter,
            "purchase_plan": self.purchase_plan,
        }


def _require_state_integer(value: object, label: str, *, minimum: int = 1) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise RecommendationError(f"decision state has invalid {label}")
    return value


def _require_state_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RecommendationError(f"decision state has invalid {label}")
    return value.strip()


def _parse_optional_state_integer(value: object, label: str) -> int | None:
    return _require_state_integer(value, label) if value is not None else None


def _parse_state_integers(value: object, label: str) -> tuple[int, ...]:
    if not isinstance(value, list):
        raise RecommendationError(f"decision state has invalid {label}")
    return tuple(_require_state_integer(item, label) for item in value)


def _parse_unique_state_integers(value: object, label: str) -> tuple[int, ...]:
    result = _parse_state_integers(value, label)
    if len(result) != len(set(result)):
        raise RecommendationError(f"decision state has duplicate {label}")
    return result


def _parse_unique_state_strings(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise RecommendationError(f"decision state has invalid {label}")
    result = tuple(str(item).strip() for item in value)
    if len(result) != len(set(result)):
        raise RecommendationError(f"decision state has duplicate {label}")
    return result


def _parse_purchase_placements(value: object) -> dict[int, int]:
    if not isinstance(value, dict):
        raise RecommendationError(
            "Placement overrides must map item IDs to checkpoints"
        )
    result = {}
    for key, position in value.items():
        if (
            not isinstance(key, str)
            or not key.isdecimal()
            or str(int(key)) != key
            or int(key) < 1
        ):
            raise RecommendationError("Placement override keys must be item IDs")
        result[int(key)] = _require_state_integer(
            position, "purchase checkpoint", minimum=0
        )
    return result


def _parse_match_economy(value: object) -> MatchEconomy | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - {
        "personal_net_worth",
        "lobby_net_worths",
        "observed_at_s",
    }:
        raise RecommendationError("Match economy has invalid fields")
    personal = value.get("personal_net_worth")
    observed = value.get("observed_at_s")
    lobby = value.get("lobby_net_worths", [])
    if not isinstance(lobby, list) or len(lobby) > 12:
        raise RecommendationError("Lobby wealth must contain at most 12 player values")
    return MatchEconomy(
        _require_state_integer(personal, "personal net worth", minimum=0)
        if personal is not None
        else None,
        tuple(
            _require_state_integer(amount, "lobby net worth", minimum=0)
            for amount in lobby
        ),
        _require_state_integer(observed, "economy observation time", minimum=0)
        if observed is not None
        else None,
    )
