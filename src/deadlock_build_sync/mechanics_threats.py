from __future__ import annotations

from .mechanics_item_text import (
    _has_ally_target,
    _material_observed_mechanics,
    _response_mechanic_labels,
    canonical_mechanics_text,
)


def classify_item_threat_responses(asset: dict[str, object]) -> frozenset[str]:
    """Map only explicit current item mechanics to conservative threat classes.

    Returns:
        Threats for which the asset text contains a direct response mechanic.

    """
    responses = set(_response_mechanic_labels(asset))
    normalized = canonical_mechanics_text(_material_observed_mechanics(asset))
    if _has_ally_target(normalized) and any(
        phrase in normalized for phrase in ("shield", "heal", "resist")
    ):
        responses.add("ally_protection")
    return frozenset(responses)


_CONDITIONAL_RESPONSE_COPY = {
    "spirit_burst": (
        "Heavy Spirit damage",
        "Before the next Spirit-heavy fight",
    ),
    "bullet_pressure": (
        "Heavy bullet damage",
        "Before the next bullet-heavy fight",
    ),
    "healing": (
        "Heavy enemy healing",
        "Before the next fight with heavy enemy healing",
    ),
    "hard_control": (
        "Hard control or debuffs",
        "Before entering the next control-heavy fight",
    ),
    "mobility_denial": (
        "Slows or movement denial",
        "Before the next fight with heavy slows",
    ),
    "slow_resistance": (
        "Enemy slows or movement denial",
        "Before the next fight with heavy slows",
    ),
    "ally_protection": (
        "A focused ally needs protection",
        "Before the ally commits to the next fight",
    ),
}
_CONDITIONAL_RESPONSE_PRIORITY = (
    "spirit_burst",
    "bullet_pressure",
    "healing",
    "hard_control",
    "slow_resistance",
    "mobility_denial",
    "ally_protection",
)
_COMPARATOR_PURPOSES = (
    (("teleport", "pull", "ground", "disarm"), "catch"),
    (("bullet resist", "spirit resist", "shield"), "survival"),
    (("cooldown", "recharge"), "ability uptime"),
    (("weapon damage", "bullet damage", "fire rate"), "weapon pressure"),
    (("spirit damage", "spirit power"), "Spirit pressure"),
    (("heal", "lifesteal", "life steal"), "sustain"),
    (("melee",), "melee pressure"),
    (("range",), "range"),
    (("slow", "stun", "silence", "root"), "control"),
)


def _selected_response(asset: dict[str, object], response: str | None) -> str | None:
    responses = classify_item_threat_responses(asset)
    selected = response or next(
        (
            candidate
            for candidate in _CONDITIONAL_RESPONSE_PRIORITY
            if candidate in responses
        ),
        None,
    )
    if selected not in responses or selected not in _CONDITIONAL_RESPONSE_COPY:
        return None
    return selected


def _response_why(asset: dict[str, object], selected: str) -> tuple[str, str] | None:
    item_text = canonical_mechanics_text(_material_observed_mechanics(asset))
    response_labels = _response_mechanic_labels(asset)
    mechanics = list(response_labels[selected])
    for candidate in _CONDITIONAL_RESPONSE_PRIORITY:
        if candidate == "ally_protection" and selected != candidate:
            continue
        for label in response_labels.get(candidate, ()):
            if label not in mechanics:
                mechanics.append(label)
    if not mechanics:
        return None
    friendly = _has_ally_target(item_text)
    self_cast = "self cast" in item_text or "self-cast" in item_text
    if friendly and self_cast:
        target = " for self/ally"
    elif friendly:
        target = " for ally"
    else:
        target = ""
    return item_text, " and ".join(mechanics[:3]) + target


def _comparator_purpose(comparator: dict[str, object]) -> str | None:
    text = canonical_mechanics_text(_material_observed_mechanics(comparator))
    return next(
        (
            label
            for phrases, label in _COMPARATOR_PURPOSES
            if any(phrase in text for phrase in phrases)
        ),
        None,
    )


def _response_copy(selected: str, item_text: str) -> tuple[str, str]:
    vs, when = _CONDITIONAL_RESPONSE_COPY[selected]
    mobility_phrases = (
        "become grounded",
        "causes grounded",
        "ground, slow",
        "disarm",
        "applies slow",
    )
    if selected == "mobility_denial" and any(
        phrase in item_text for phrase in mobility_phrases
    ):
        return "Enemy escape or mobility", "Before fighting an evasive target"
    return vs, when


def conditional_item_decision(
    asset: dict[str, object],
    comparator: dict[str, object],
    *,
    response: str | None = None,
) -> tuple[str, str, str, str] | None:
    """Build grounded VS, WHY, WHEN, and SKIP fields from pinned mechanics.

    Returns:
        The four fields, or ``None`` when either item purpose is not explicit.

    """
    selected = _selected_response(asset, response)
    if selected is None:
        return None
    response_result = _response_why(asset, selected)
    if response_result is None:
        return None
    item_text, why = response_result
    purpose = _comparator_purpose(comparator)
    if purpose is None:
        return None
    vs, when = _response_copy(selected, item_text)
    return vs, why, when, f"Keep default when {purpose} matters more"
