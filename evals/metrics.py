from __future__ import annotations

import json
import re
from itertools import combinations, starmap
from typing import TYPE_CHECKING, Any, override

from deepeval.metrics import BaseMetric

from scripts import generate_narratives

if TYPE_CHECKING:
    from collections.abc import Iterable

    from deepeval.test_case import LLMTestCase

QUARTERS = ("I", "II", "III", "IV")
QUARTER_INDEX = {quarter: index for index, quarter in enumerate(QUARTERS)}
DECISION_PATTERN = re.compile(
    r"\b(?:after|before|if|once|only|save|hold|until|when|while|unless|then)\b"
    r"|rather than|as soon as",
    re.IGNORECASE,
)
POSITION_PATTERN = re.compile(
    r"\b(?:all(?:y|ies)|angle|backline|behind|cluster|commit|disengage|"
    r"enem(?:y|ies)|engage|exposed|flank|frontline|group|near|position|range|reset|"
    r"retreat|safe|target|team)\w*\b",
    re.IGNORECASE,
)
STAGE_PATTERNS = {
    "I": re.compile(
        r"\b(?:economy|establish|farm|income|jungle|lane|pressure|survive|trade)\w*\b",
        re.IGNORECASE,
    ),
    "II": re.compile(
        r"\b(?:accelerate|farm|fight|gank|group|objective|pressure|roam|rotate|"
        r"skirmish)\w*\b",
        re.IGNORECASE,
    ),
    "III": re.compile(
        r"\b(?:convert|economy|farm|fight|force|group|objective|pick|pressure|"
        r"scale)\w*\b",
        re.IGNORECASE,
    ),
    "IV": re.compile(
        r"\b(?:close|convert|end|fight|group|objective|push|reset)\w*\b",
        re.IGNORECASE,
    ),
}
MACRO_PATTERNS = {
    "lane": re.compile(r"\b(?:lane|laning)\b", re.IGNORECASE),
    "economy": re.compile(r"\b(?:economy|farm|income|jungle)\w*\b", re.IGNORECASE),
    "roam": re.compile(r"\b(?:gank|invade|roam|rotat)\w*\b", re.IGNORECASE),
    "pick": re.compile(r"\bpick\w*\b", re.IGNORECASE),
    "group": re.compile(r"\bgroup\w*\b", re.IGNORECASE),
    "objective": re.compile(r"\bobjective\w*\b", re.IGNORECASE),
    "engage": re.compile(
        r"\b(?:commit|counter-engage|engage|fight|initiate|peel)\w*\b",
        re.IGNORECASE,
    ),
    "pressure": re.compile(r"\b(?:force|pressure)\w*\b", re.IGNORECASE),
    "reset": re.compile(r"\b(?:disengage|reset|retreat)\w*\b", re.IGNORECASE),
    "close": re.compile(r"\b(?:close|convert|end|push)\w*\b", re.IGNORECASE),
}
TACTICAL_PERMISSION_PATTERNS = {
    "objective_force": re.compile(
        r"\b(?:boss|objective|patron|structure)\w*\b|\bconvert\w*\b",
        re.IGNORECASE,
    ),
    "counter_engage": re.compile(r"\bcounter[ -]?engag\w*\b", re.IGNORECASE),
    "teamfight_control": re.compile(
        r"\b(?:area control|area denial|cluster|control|freeze|slow|teamfight|"
        r"zone)\w*\b",
        re.IGNORECASE,
    ),
    "survivability": re.compile(
        r"\b(?:barrier|cleanse|dome|protect|purge|rescue|safe|shelter|stabili|"
        r"surviv)\w*\b",
        re.IGNORECASE,
    ),
    "sustain": re.compile(
        r"\b(?:heal|lifesteal|regen|restor|sustain)\w*\b",
        re.IGNORECASE,
    ),
    "mobility_access": re.compile(
        r"\b(?:access|chase|escape|mobility|move speed|path|reposition|rotate)\w*\b",
        re.IGNORECASE,
    ),
    "pick_creation": re.compile(
        r"\b(?:assassin|gank|isolated|pick)\w*\b",
        re.IGNORECASE,
    ),
    "disengage_reset": re.compile(
        r"\b(?:disengage|re-engage|reset|retreat)\w*\b",
        re.IGNORECASE,
    ),
    "pressure_close": re.compile(
        r"\b(?:close|end|finish|force|pressure)\w*\b",
        re.IGNORECASE,
    ),
    "repeatable_uptime": re.compile(
        r"\b(?:available|charge|cooldown|cycle|repeat|uptime)\w*\b",
        re.IGNORECASE,
    ),
}
MECHANIC_PATTERNS = {
    "area": re.compile(r"\b(?:area|coverage|enlarg|radius|zone)\w*\b", re.IGNORECASE),
    "charges": re.compile(r"\b(?:charge|recharge)\w*\b", re.IGNORECASE),
    "cleanse": re.compile(r"\b(?:cleanse|purge)\w*\b", re.IGNORECASE),
    "control": re.compile(
        r"\b(?:control|freeze|immobili|root|slow|suppress)\w*\b",
        re.IGNORECASE,
    ),
    "cooldown": re.compile(
        r"\b(?:available|cooldown|cycle|frequency|repeat)\w*\b", re.IGNORECASE
    ),
    "damage": re.compile(r"\b(?:damage|dps)\w*\b", re.IGNORECASE),
    "disarm": re.compile(r"\bdisarm\w*\b", re.IGNORECASE),
    "fire_rate": re.compile(r"\b(?:attack|fire) rate\b", re.IGNORECASE),
    "healing": re.compile(r"\b(?:heal|lifesteal|regen|restor)\w*\b", re.IGNORECASE),
    "mobility": re.compile(
        r"\b(?:dash|escape|mobility|move speed|path|reposition|sprint)\w*\b",
        re.IGNORECASE,
    ),
    "protection": re.compile(
        r"\b(?:barrier|impenetrable|protect|resist|shelter|surviv)\w*\b",
        re.IGNORECASE,
    ),
    "range": re.compile(r"\b(?:range|reach)\w*\b", re.IGNORECASE),
    "scaling": re.compile(
        r"\b(?:amp|scal)\w*\b|\bspirit(?:[- ](?:based|control|damage|enhance\w*|"
        r"focus\w*|heal\w*|output|package|power|pressure|scal\w*))\b",
        re.IGNORECASE,
    ),
    "silence": re.compile(r"\bsilenc\w*\b", re.IGNORECASE),
    "stealth": re.compile(r"\b(?:invisib|stealth|undetect)\w*\b", re.IGNORECASE),
    "stun": re.compile(r"\bstun\w*\b", re.IGNORECASE),
}
HARD_UNSUPPORTED_MECHANICS = {"cleanse", "disarm", "silence", "stealth", "stun"}
QUARTER_PROXIMITY = {0: 1.0, 1: 0.9, 2: 0.25, 3: 0.0}
CHARGE_QUALIFICATION_PATTERN = re.compile(
    r"\b(?:ability\s*charges?\b(?!\s+up\b)|charged abilities\b"
    r"|allow(?:s|ed|ing)?\s+charges?\b)",
    re.IGNORECASE,
)


def _mentions_name(text: str, name: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text) is not None


def _parse_object(output: str | None) -> tuple[dict[str, Any] | None, str | None]:
    try:
        parsed = json.loads(output or "")
    except json.JSONDecodeError as error:
        return None, str(error)
    if not isinstance(parsed, dict):
        return None, "Codex response was not a JSON object"
    return parsed, None


def _quarter_texts(response: dict[str, Any]) -> dict[str, str] | None:
    quarters = response.get("quarters")
    if not isinstance(quarters, dict):
        return None
    if any(not isinstance(quarters.get(quarter), str) for quarter in QUARTERS):
        return None
    return {quarter: str(quarters[quarter]) for quarter in QUARTERS}


def _tier_item_names(hero: dict[str, Any]) -> dict[str, list[str]]:
    tiers = hero.get("tiers")
    if not isinstance(tiers, dict):
        return {quarter: [] for quarter in QUARTERS}
    return {
        quarter: [
            str(item.get("item") or "").strip()
            for item in tiers.get(quarter, [])
            if isinstance(item, dict) and str(item.get("item") or "").strip()
        ]
        if isinstance(tiers.get(quarter), list)
        else []
        for quarter in QUARTERS
    }


def _step_ability_names(hero: dict[str, Any]) -> dict[str, set[str]]:
    result = {quarter: set[str]() for quarter in QUARTERS}
    ability_path = hero.get("ability_path")
    steps = ability_path.get("steps") if isinstance(ability_path, dict) else None
    if not isinstance(steps, list):
        return result
    for step in steps:
        if not isinstance(step, dict) or not isinstance(step.get("quarter"), int):
            continue
        quarter_number = int(step["quarter"])
        ability = str(step.get("ability") or "").strip()
        if 1 <= quarter_number <= len(QUARTERS) and ability:
            result[QUARTERS[quarter_number - 1]].add(ability)
    return result


def _first_ability_quarters(hero: dict[str, Any]) -> dict[str, str]:
    first_quarters: dict[str, str] = {}
    for quarter, names in _step_ability_names(hero).items():
        for name in names:
            first_quarters.setdefault(name, quarter)
    return first_quarters


def _macro_features(text: str) -> set[str]:
    return {label for label, pattern in MACRO_PATTERNS.items() if pattern.search(text)}


def _tier_three_macro_identity(
    features: set[str],
    hero: dict[str, Any],
) -> str:
    curve = hero.get("duration_curve")
    shape = curve.get("shape") if isinstance(curve, dict) else None
    preserves_economy = bool(features & {"economy", "lane"})
    seeks_conversion = bool(
        features & {"close", "engage", "group", "objective", "pick", "pressure"}
    )
    if shape != "LATE_SCALING":
        return "convert_supported_timing" if seeks_conversion else "other_pressure"
    identities = {
        (True, True): "scale_and_convert",
        (True, False): "scale_only",
        (False, True): "force_without_economy",
        (False, False): "other_pressure",
    }
    return identities[preserves_economy, seeks_conversion]


def _macro_stage_identity(
    text: str,
    quarter: str,
    hero: dict[str, Any],
) -> str:
    features = _macro_features(text)
    if quarter == "I":
        return (
            "economy_establish"
            if features & {"economy", "lane"}
            else "pressure_establish"
            if features & {"engage", "pressure"}
            else "other_establish"
        )
    if quarter == "II":
        return (
            "coordinated_acceleration"
            if features & {"engage", "group", "objective", "roam"}
            else "economy_acceleration"
            if features & {"economy", "lane"}
            else "other_acceleration"
        )
    if quarter == "III":
        return _tier_three_macro_identity(features, hero)
    return (
        "close"
        if features & {"close"}
        else "objective_without_close"
        if features & {"objective"}
        else "fight_without_close"
        if features & {"engage", "reset"}
        else "other_close"
    )


def _macro_identity_stability(
    outputs: list[dict[str, Any]],
    hero: dict[str, Any],
) -> float:
    quarter_texts = [
        texts for output in outputs if (texts := _quarter_texts(output)) is not None
    ]
    if len(quarter_texts) != len(outputs) or len(outputs) < 2:
        return 0.0
    quarter_scores = []
    for quarter in QUARTERS:
        identities = [
            _macro_stage_identity(texts[quarter], quarter, hero)
            for texts in quarter_texts
        ]
        pairs = list(combinations(identities, 2))
        quarter_scores.append(_fraction(left == right for left, right in pairs))
    return _fraction(quarter_scores)


def _tier_quality_violations(
    response: dict[str, Any],
    hero: dict[str, Any],
) -> list[str]:
    quarter_texts = _quarter_texts(response)
    if quarter_texts is None:
        return ["response omitted the four tier instructions"]
    tier_items = _tier_item_names(hero)
    step_abilities = _step_ability_names(hero)
    first_item_quarters = {
        name: quarter for quarter in QUARTERS for name in tier_items[quarter]
    }
    first_ability_quarters = _first_ability_quarters(hero)
    violations: list[str] = []
    for quarter, text in quarter_texts.items():
        mentioned_tier_items = [
            name for name in tier_items[quarter] if _mentions_name(text, name)
        ]
        if not 1 <= len(mentioned_tier_items) <= 3:
            violations.append(
                f"Tier {quarter} must explain one to three same-tier items"
            )
        if step_abilities[quarter] and not any(
            _mentions_name(text, ability) for ability in step_abilities[quarter]
        ):
            violations.append(
                f"Tier {quarter} omitted every ability from its ability-order steps"
            )
        future_items = [
            name
            for name, first_quarter in first_item_quarters.items()
            if QUARTER_INDEX[first_quarter] > QUARTER_INDEX[quarter]
            and _mentions_name(text, name)
        ]
        if future_items:
            violations.append(
                f"Tier {quarter} mentioned future item(s): {', '.join(future_items)}"
            )
        future_abilities = [
            name
            for name, first_quarter in first_ability_quarters.items()
            if QUARTER_INDEX[first_quarter] > QUARTER_INDEX[quarter]
            and _mentions_name(text, name)
        ]
        if future_abilities:
            violations.append(
                f"Tier {quarter} mentioned future ability(s): "
                + ", ".join(future_abilities)
            )
        if STAGE_PATTERNS[quarter].search(text) is None:
            violations.append(f"Tier {quarter} omitted its stage-specific macro goal")
        if DECISION_PATTERN.search(text) is None:
            violations.append(f"Tier {quarter} omitted a timing or decision condition")
        if POSITION_PATTERN.search(text) is None:
            violations.append(
                f"Tier {quarter} omitted positioning, targeting, or an exit condition"
            )
    return violations


def _curve_pressure_pattern(hero: dict[str, Any]) -> re.Pattern[str]:
    curve = hero.get("duration_curve")
    shape = curve.get("shape") if isinstance(curve, dict) else None
    if shape == "LATE_SCALING":
        return re.compile(
            r"\b(?:economy|farm|patient|preserve)\w*\b",
            re.IGNORECASE,
        )
    if shape == "EARLY_CLOSER":
        return re.compile(
            r"\b(?:accelerate|close|convert|force|objective|pressure)\w*\b",
            re.IGNORECASE,
        )
    return re.compile(
        r"\b(?:convert|economy|flexible|objective|pick|pressure)\w*\b",
        re.IGNORECASE,
    )


def _progression_violations(
    response: dict[str, Any],
    hero: dict[str, Any],
) -> list[str]:
    quarter_texts = _quarter_texts(response)
    if quarter_texts is None:
        return ["response omitted the four tier instructions"]
    violations: list[str] = []
    macro_signatures = {
        tuple(sorted(_macro_features(text))) for text in quarter_texts.values()
    }
    if len(macro_signatures) < 3:
        violations.append("fewer than three distinct macro stages across four tiers")
    if _curve_pressure_pattern(hero).search(quarter_texts["III"]) is None:
        violations.append("Tier III did not adapt pressure to the duration curve")
    if (
        re.search(
            r"\b(?:close|convert|end|objective|push)\w*\b",
            quarter_texts["IV"],
            re.IGNORECASE,
        )
        is None
    ):
        violations.append("Tier IV omitted a concrete close-out instruction")
    sentences = [
        re.sub(r"\s+", " ", sentence.strip().casefold())
        for text in quarter_texts.values()
        for sentence in re.split(r"[.!?]+", text)
        if len(sentence.strip()) >= 30
    ]
    if len(sentences) != len(set(sentences)):
        violations.append("the tier plan repeats a full instruction across stages")
    return violations


class _SynchronousNarrativeMetric(BaseMetric):
    metric_name = "Narrative metric"

    def __init__(self, hero: dict[str, Any], *, threshold: float = 1.0) -> None:
        self.hero = hero
        self.threshold = threshold
        self.async_mode = False
        self.include_reason = True

    @property
    @override
    def __name__(self) -> str:
        """The metric's display name.

        Returns:
            The report label configured by the subclass.

        """
        return self.metric_name

    @override
    async def a_measure(
        self,
        test_case: LLMTestCase,
        *_args: Any,
        **_kwargs: Any,
    ) -> float:
        """Run the deterministic synchronous metric in async evaluations.

        Returns:
            The metric score.

        """
        return self.measure(test_case)

    @override
    def is_successful(self) -> bool:
        """Report whether the latest measurement passed.

        Returns:
            Whether the metric reached its threshold.

        """
        return self.success is True

    def _record(self, score: float, reason: str) -> float:
        self.score = score
        self.success = score >= self.threshold
        self.reason = reason
        return score


class ProductionContractMetric(_SynchronousNarrativeMetric):
    """Apply the complete production validator as a DeepEval metric."""

    metric_name = "Production contract"

    @override
    def measure(
        self,
        test_case: LLMTestCase,
        *_args: Any,
        **_kwargs: Any,
    ) -> float:
        """Validate one structured response.

        Returns:
            One for a valid production response, otherwise zero.

        """
        response, error = _parse_object(test_case.actual_output)
        if response is None:
            return self._record(0.0, error or "invalid response")
        try:
            generate_narratives.validate_response(response, self.hero)
        except generate_narratives.GenerationError as validation_error:
            return self._record(0.0, str(validation_error))
        return self._record(1.0, "Production narrative validator passed")


class PerTierTacticalQualityMetric(_SynchronousNarrativeMetric):
    """Check actionable tactical content independently for all four tiers."""

    metric_name = "Per-tier tactical quality"

    @override
    def measure(
        self,
        test_case: LLMTestCase,
        *_args: Any,
        **_kwargs: Any,
    ) -> float:
        """Score all tier instructions against deterministic tactical rules.

        Returns:
            One when every tier meets the rubric, otherwise zero.

        """
        response, error = _parse_object(test_case.actual_output)
        if response is None:
            return self._record(0.0, error or "invalid response")
        violations = _tier_quality_violations(response, self.hero)
        if violations:
            return self._record(0.0, "; ".join(violations))
        return self._record(1.0, "All four tiers are actionable and stage-correct")


class CrossTierProgressionMetric(_SynchronousNarrativeMetric):
    """Check that the four instructions form an evolving game plan."""

    metric_name = "Cross-tier progression"

    @override
    def measure(
        self,
        test_case: LLMTestCase,
        *_args: Any,
        **_kwargs: Any,
    ) -> float:
        """Score progression from establish through close.

        Returns:
            One when the four stages progress coherently, otherwise zero.

        """
        response, error = _parse_object(test_case.actual_output)
        if response is None:
            return self._record(0.0, error or "invalid response")
        violations = _progression_violations(response, self.hero)
        if violations:
            return self._record(0.0, "; ".join(violations))
        return self._record(1.0, "The plan progresses from establish to close")


def _fraction(values: Iterable[bool | float]) -> float:
    materialized = list(values)
    return sum(materialized) / len(materialized) if materialized else 1.0


def _mentioned_names(text: str, names: Iterable[str]) -> set[str]:
    return {name for name in names if _mentions_name(text, name)}


def _mentioned_ability_names(text: str, names: Iterable[str]) -> set[str]:
    materialized = list(names)
    mentioned = _mentioned_names(text, materialized)
    trailing_names = {
        name: name.rsplit(maxsplit=1)[-1]
        for name in materialized
        if len(name.rsplit(maxsplit=1)) > 1
    }
    for name, trailing in trailing_names.items():
        if (
            name not in mentioned
            and len(trailing) >= 4
            and sum(
                candidate.casefold() == trailing.casefold()
                for candidate in trailing_names.values()
            )
            == 1
            and _mentions_name(text, trailing)
        ):
            mentioned.add(name)
    return mentioned


def _context_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_context_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_context_text(item) for item in value)
    if isinstance(value, str | int | float):
        return str(value)
    return ""


def _features(text: str, patterns: dict[str, re.Pattern[str]]) -> set[str]:
    return {name for name, pattern in patterns.items() if pattern.search(text)}


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _pairwise_jaccard(feature_sets: list[set[str]]) -> float:
    pairs = list(combinations(feature_sets, 2))
    return sum(starmap(_jaccard, pairs)) / len(pairs) if pairs else 0.0


def _pairwise_containment(feature_sets: list[set[str]]) -> float:
    pairs = list(combinations(feature_sets, 2))
    if not pairs:
        return 0.0
    scores = [
        len(left & right) / min(len(left), len(right)) if left and right else 0.0
        for left, right in pairs
    ]
    return sum(scores) / len(scores)


def _majority_containment(feature_sets: list[set[str]]) -> float:
    if len(feature_sets) < 2:
        return 0.0
    majority_count = (len(feature_sets) // 2) + 1
    majority = {
        feature
        for feature in set().union(*feature_sets)
        if sum(feature in features for features in feature_sets) >= majority_count
    }
    if not majority:
        return 0.0
    return sum(
        len(features & majority) / len(majority) for features in feature_sets
    ) / len(feature_sets)


def _power_spikes(output: dict[str, Any]) -> list[dict[str, Any]]:
    profile = output.get("tactical_profile")
    spikes = profile.get("power_spikes") if isinstance(profile, dict) else None
    if not isinstance(spikes, list):
        return []
    return [spike for spike in spikes if isinstance(spike, dict)]


def _timing_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0

    def best(source: str, targets: set[str]) -> float:
        source_index = QUARTER_INDEX.get(source)
        if source_index is None:
            return 0.0
        proximities = [
            QUARTER_PROXIMITY[abs(source_index - QUARTER_INDEX[target])]
            for target in targets
            if target in QUARTER_INDEX
        ]
        return max(proximities, default=0.0)

    directed = [
        *[best(quarter, right) for quarter in left],
        *[best(quarter, left) for quarter in right],
    ]
    return sum(directed) / len(directed)


def _pairwise_timing_stability(outputs: list[dict[str, Any]]) -> float:
    quarter_sets = [
        {
            str(spike.get("quarter"))
            for spike in _power_spikes(output)
            if spike.get("quarter") in QUARTER_INDEX
        }
        for output in outputs
    ]
    pairs = list(combinations(quarter_sets, 2))
    return sum(starmap(_timing_similarity, pairs)) / len(pairs) if pairs else 0.0


def _tactical_stability(outputs: list[dict[str, Any]]) -> float:
    feature_sets = [
        _features(
            " ".join(str(spike.get("tactical_unlock") or "") for spike in spikes),
            TACTICAL_PERMISSION_PATTERNS,
        )
        for output in outputs
        if (spikes := _power_spikes(output))
    ]
    if len(feature_sets) != len(outputs):
        return 0.0
    return _majority_containment(feature_sets)


def _mentions_upgrade(text: str, upgrade: str) -> bool:
    if upgrade == "UNLOCK":
        return re.search(r"\bunlock\w*\b", text, re.IGNORECASE) is not None
    return (
        re.search(rf"(?<!\w){re.escape(upgrade)}(?!\w)", text, re.IGNORECASE)
        is not None
    )


def _ability_source_text(ability: dict[str, Any], upgrade: str | None) -> str:
    description = ability.get("description")
    if not isinstance(description, dict):
        return _context_text(ability)
    selected = [str(ability.get("ability") or "")]
    selected.extend(str(description.get(field) or "") for field in ("desc", "quip"))
    selected.append(_context_text(ability.get("stats")))
    if upgrade and upgrade != "UNLOCK":
        selected.append(str(description.get(f"{upgrade.casefold()}_desc") or ""))
    return " ".join(selected)


def _has_outcome_evidence(value: dict[str, Any]) -> bool:
    return (
        isinstance(value.get("raw_win_rate"), int | float)
        and isinstance(value.get("matches"), int)
        and value["matches"] > 0
    )


def _duration_has_outcome_evidence(hero: dict[str, Any]) -> bool:
    curve = hero.get("duration_curve")
    phases = curve.get("phases") if isinstance(curve, dict) else None
    return isinstance(phases, list) and any(
        isinstance(phase, dict) and _has_outcome_evidence(phase) for phase in phases
    )


def _mechanic_grounding_violations(
    selected_item: dict[str, Any],
    selected_ability: dict[str, Any],
    selected_upgrade: str | None,
    trigger: str,
    tactical_unlock: str,
) -> list[str]:
    item_text = _context_text(selected_item)
    ability_text = _ability_source_text(selected_ability, selected_upgrade)
    item_features = _features(item_text, MECHANIC_PATTERNS)
    ability_features = _features(
        ability_text,
        MECHANIC_PATTERNS,
    )
    claimed_features = _features(f"{trigger} {tactical_unlock}", MECHANIC_PATTERNS)
    unlock_features = _features(tactical_unlock, MECHANIC_PATTERNS)
    supported_features = item_features | ability_features
    unsupported = (unlock_features - supported_features) & HARD_UNSUPPORTED_MECHANICS
    violations: list[str] = []
    if not claimed_features:
        violations.append("tactical unlock states no supported item/ability mechanic")
    if not item_features & claimed_features:
        violations.append("selected item does not support the claimed unlock")
    if not ability_features & claimed_features:
        violations.append("selected ability does not support the claimed unlock")
    if CHARGE_QUALIFICATION_PATTERN.search(item_text) and not (
        CHARGE_QUALIFICATION_PATTERN.search(ability_text)
    ):
        violations.append("charge-specific item does not support the selected ability")
    if unsupported:
        violations.append("unsupported mechanic(s): " + ", ".join(sorted(unsupported)))
    return violations


def _power_spike_grounding(
    outputs: list[dict[str, Any]],
    hero: dict[str, Any],
) -> tuple[float, float, list[str]]:
    tiers = hero.get("tiers")
    tier_items = tiers if isinstance(tiers, dict) else {}
    all_items = [
        (quarter, item)
        for quarter in QUARTERS
        for item in tier_items.get(quarter, [])
        if isinstance(item, dict) and str(item.get("item") or "").strip()
    ]
    abilities = [
        ability
        for ability in hero.get("abilities", [])
        if isinstance(ability, dict) and str(ability.get("ability") or "").strip()
    ]
    ability_path = hero.get("ability_path")
    steps = ability_path.get("steps") if isinstance(ability_path, dict) else None
    path_steps = (
        [step for step in steps if isinstance(step, dict)]
        if isinstance(steps, list)
        else []
    )
    path_has_evidence = isinstance(ability_path, dict) and _has_outcome_evidence(
        ability_path
    )
    curve_has_evidence = _duration_has_outcome_evidence(hero)
    output_grounding: list[bool] = []
    evidence_links: list[bool] = []
    violations: list[str] = []

    for generation, output in enumerate(outputs, start=1):
        spikes = _power_spikes(output)
        if not 1 <= len(spikes) <= 2:
            output_grounding.append(False)
            violations.append(f"generation {generation} omitted one or two spikes")
            evidence_links.extend((False, path_has_evidence, curve_has_evidence))
            continue
        generation_grounded = True
        for spike in spikes:
            quarter = str(spike.get("quarter") or "")
            trigger = str(spike.get("trigger") or "")
            tactical_unlock = str(spike.get("tactical_unlock") or "")
            label = f"generation {generation} Tier {quarter or '?'}"
            spike_violations: list[str] = []
            mentioned_items = [
                (item_quarter, item)
                for item_quarter, item in all_items
                if _mentions_name(trigger, str(item["item"]))
            ]
            selected_item = mentioned_items[0][1] if len(mentioned_items) == 1 else None
            core_items = [
                item
                for item in tier_items.get(quarter, [])[:3]
                if isinstance(item, dict)
            ]
            if (
                len(mentioned_items) != 1
                or mentioned_items[0][0] != quarter
                or selected_item not in core_items
            ):
                spike_violations.append(
                    "trigger must name exactly one top-three same-tier item"
                )

            mentioned_abilities = [
                ability
                for ability in abilities
                if _mentions_name(trigger, str(ability["ability"]))
            ]
            selected_ability = (
                mentioned_abilities[0] if len(mentioned_abilities) == 1 else None
            )
            selected_upgrade: str | None = None
            if selected_ability is None:
                spike_violations.append(
                    "trigger must name exactly one supplied ability"
                )
            elif path_steps:
                matching_steps = [
                    step
                    for step in path_steps
                    if step.get("quarter") == QUARTER_INDEX.get(quarter, -1) + 1
                    and step.get("ability") == selected_ability.get("ability")
                ]
                mentioned_steps = [
                    step
                    for step in matching_steps
                    if isinstance(step.get("upgrade"), str)
                    and _mentions_upgrade(trigger, str(step["upgrade"]))
                ]
                if len(mentioned_steps) != 1:
                    spike_violations.append(
                        "trigger must name one real same-tier ability milestone"
                    )
                else:
                    selected_upgrade = str(mentioned_steps[0]["upgrade"])

            if selected_item is not None and selected_ability is not None:
                spike_violations.extend(
                    _mechanic_grounding_violations(
                        selected_item,
                        selected_ability,
                        selected_upgrade,
                        trigger,
                        tactical_unlock,
                    )
                )

            evidence_links.extend((
                selected_item is not None and _has_outcome_evidence(selected_item),
                path_has_evidence,
                curve_has_evidence,
            ))
            if spike_violations:
                generation_grounded = False
                violations.append(f"{label}: " + "; ".join(spike_violations))
        output_grounding.append(generation_grounded)

    grounding = _fraction(output_grounding)
    evidence_coverage = _fraction(evidence_links)
    return grounding, evidence_coverage, violations


def _duration_curve_grounding(
    outputs: list[dict[str, Any]],
    hero: dict[str, Any],
) -> tuple[float, list[str]]:
    curve = hero.get("duration_curve")
    expected = curve if isinstance(curve, dict) else {}
    results: list[bool] = []
    violations: list[str] = []
    deliberate_stall = re.compile(
        r"\b(?:deliberately|intentionally)\s+(?:delay|stall)\w*\b|"
        r"\brefus\w*\b.{0,40}\b(?:close|end|finish)\w*\b",
        re.IGNORECASE,
    )
    for generation, output in enumerate(outputs, start=1):
        profile = output.get("tactical_profile")
        plan = profile.get("duration_plan") if isinstance(profile, dict) else None
        current_violations: list[str] = []
        if not isinstance(plan, dict):
            current_violations.append("missing duration plan")
        else:
            current_violations.extend(
                f"changed duration {field}"
                for field in ("shape", "strongest_phase", "weakest_phase")
                if plan.get(field) != expected.get(field)
            )
            macro_plan = str(plan.get("macro_plan") or "")
            if deliberate_stall.search(macro_plan):
                current_violations.append("advises deliberately stalling a close")
            shape = expected.get("shape")
            if shape == "LATE_SCALING":
                if (
                    re.search(
                        r"\b(?:economy|farm|late|patient|preserve|retain|scale)\w*\b",
                        macro_plan,
                        re.IGNORECASE,
                    )
                    is None
                ):
                    current_violations.append("omits the supported scaling plan")
                if (
                    re.search(
                        r"\b(?:close|convert|end|finish|objective|pick)\w*\b",
                        macro_plan,
                        re.IGNORECASE,
                    )
                    is None
                ):
                    current_violations.append("omits earlier conversion opportunities")
            elif (
                shape == "EARLY_CLOSER"
                and re.search(
                    r"\b(?:close|convert|end|force|objective|pressure)\w*\b",
                    macro_plan,
                    re.IGNORECASE,
                )
                is None
            ):
                current_violations.append("omits the supported early conversion plan")
            elif (
                shape == "MIDGAME_PEAK"
                and re.search(
                    r"\b(?:convert|midgame|objective|pressure)\w*\b",
                    macro_plan,
                    re.IGNORECASE,
                )
                is None
            ):
                current_violations.append("omits the supported midgame conversion plan")
        results.append(not current_violations)
        violations.extend(
            f"generation {generation}: {violation}" for violation in current_violations
        )
    return _fraction(results), violations


def _power_spike_identity(
    outputs: list[dict[str, Any]],
    hero: dict[str, Any],
) -> tuple[float, float, float, float]:
    item_names = [name for names in _tier_item_names(hero).values() for name in names]
    ability_names = [
        str(ability.get("ability") or "")
        for ability in hero.get("abilities", [])
        if isinstance(ability, dict) and str(ability.get("ability") or "")
    ]
    triggers = [
        " ".join(str(spike.get("trigger") or "") for spike in _power_spikes(output))
        for output in outputs
    ]
    quarter_sets = [
        {str(spike.get("quarter")) for spike in _power_spikes(output)}
        for output in outputs
    ]
    item_sets = [_mentioned_names(trigger, item_names) for trigger in triggers]
    ability_sets = [_mentioned_names(trigger, ability_names) for trigger in triggers]
    quarter_identity = _pairwise_jaccard(quarter_sets)
    item_identity = _pairwise_jaccard(item_sets)
    ability_identity = _pairwise_jaccard(ability_sets)
    exact_identity = (quarter_identity + item_identity + ability_identity) / 3
    return exact_identity, quarter_identity, item_identity, ability_identity


def _outcome_evidence_summary(
    outputs: list[dict[str, Any]],
    hero: dict[str, Any],
) -> str:
    trigger_text = " ".join(
        str(spike.get("trigger") or "")
        for output in outputs
        for spike in _power_spikes(output)
    )
    item_evidence: list[str] = []
    tiers = hero.get("tiers")
    if isinstance(tiers, dict):
        for quarter in QUARTERS:
            items = tiers.get(quarter)
            if not isinstance(items, list):
                continue
            for item in items:
                if (
                    not isinstance(item, dict)
                    or not _has_outcome_evidence(item)
                    or not _mentions_name(trigger_text, str(item.get("item") or ""))
                ):
                    continue
                item_evidence.append(
                    f"{quarter} {item['item']}={100 * float(item['raw_win_rate']):.1f}%/"
                    f"{item['matches']}"
                )
    links = ["items " + ", ".join(item_evidence)] if item_evidence else []
    ability_path = hero.get("ability_path")
    if isinstance(ability_path, dict) and _has_outcome_evidence(ability_path):
        links.append(
            "ability path="
            f"{100 * float(ability_path['raw_win_rate']):.1f}%/"
            f"{ability_path['matches']}"
        )
    curve = hero.get("duration_curve")
    phases = curve.get("phases") if isinstance(curve, dict) else None
    strongest = curve.get("strongest_phase") if isinstance(curve, dict) else None
    if isinstance(phases, list) and isinstance(strongest, str):
        phase = next(
            (
                candidate
                for candidate in phases
                if isinstance(candidate, dict)
                and candidate.get("label") == strongest
                and _has_outcome_evidence(candidate)
            ),
            None,
        )
        if phase is not None:
            links.append(
                f"hero {strongest}={100 * float(phase['raw_win_rate']):.1f}%/"
                f"{phase['matches']}"
            )
    return "; ".join(links)


def _intersection_fraction(sets_by_quarter: dict[str, list[set[str]]]) -> float:
    applicable = [sets for sets in sets_by_quarter.values() if sets]
    return _fraction(
        bool(set.intersection(*sets)) if all(sets) else False for sets in applicable
    )


def _pairwise_quarter_containment(
    sets_by_quarter: dict[str, list[set[str]]],
) -> float:
    applicable = [sets for sets in sets_by_quarter.values() if sets]
    return _fraction(_pairwise_containment(sets) for sets in applicable)


def _majority_quarter_support(
    sets_by_quarter: dict[str, list[set[str]]],
) -> float:
    applicable = [sets for sets in sets_by_quarter.values() if sets]
    quarter_scores = []
    for feature_sets in applicable:
        majority_count = (len(feature_sets) // 2) + 1
        consensus = {
            feature
            for feature in set().union(*feature_sets)
            if sum(feature in features for features in feature_sets) >= majority_count
        }
        quarter_scores.append(
            _fraction(bool(features & consensus) for features in feature_sets)
        )
    return _fraction(quarter_scores)


class RepeatedGenerationStabilityMetric(_SynchronousNarrativeMetric):
    """Score completion and tactical consistency across repeated generations."""

    metric_name = "Repeated-generation stability"

    def __init__(self, hero: dict[str, Any]) -> None:
        super().__init__(hero, threshold=0.9)

    @override
    def measure(
        self,
        test_case: LLMTestCase,
        *_args: Any,
        **_kwargs: Any,
    ) -> float:
        """Compare repeated outputs by contract and semantic features.

        Returns:
            A zero-to-one reliability score across all samples.

        """
        try:
            samples = json.loads(test_case.actual_output or "")
        except json.JSONDecodeError as error:
            return self._record(0.0, str(error))
        if not isinstance(samples, list) or len(samples) < 2:
            return self._record(0.0, "Reliability output did not contain repeats")
        outputs = [
            sample["output"]
            for sample in samples
            if isinstance(sample, dict) and isinstance(sample.get("output"), dict)
        ]
        completion = len(outputs) / len(samples)
        contracts: list[bool] = []
        for output in outputs:
            try:
                generate_narratives.validate_response(output, self.hero)
            except generate_narratives.GenerationError:
                contracts.append(False)
            else:
                contracts.append(True)
        contract = sum(contracts) / len(samples)
        tier_violation_sets = [
            _tier_quality_violations(output, self.hero) for output in outputs
        ]
        progression_violation_sets = [
            _progression_violations(output, self.hero) for output in outputs
        ]
        tier_quality = sum(not violations for violations in tier_violation_sets) / len(
            samples
        )
        progression = sum(
            not violations for violations in progression_violation_sets
        ) / len(samples)

        curve_responses = {
            output
            .get("tactical_profile", {})
            .get("duration_plan", {})
            .get("late_build_response")
            for output in outputs
        }
        tier_items = _tier_item_names(self.hero)
        ability_names = [
            str(ability.get("ability") or "").strip()
            for ability in self.hero.get("abilities", [])
            if isinstance(ability, dict) and str(ability.get("ability") or "").strip()
        ]
        quarter_texts = [
            texts for output in outputs if (texts := _quarter_texts(output)) is not None
        ]
        item_sets = {
            quarter: [
                _mentioned_names(texts[quarter], tier_items[quarter])
                for texts in quarter_texts
            ]
            for quarter in QUARTERS
        }
        ability_sets = {
            quarter: [
                _mentioned_ability_names(texts[quarter], ability_names)
                for texts in quarter_texts
            ]
            for quarter in QUARTERS
        }
        macro_sets = {
            quarter: [_macro_features(texts[quarter]) for texts in quarter_texts]
            for quarter in QUARTERS
        }
        enough_outputs = len(outputs) >= 2
        timing_stability = (
            _pairwise_timing_stability(outputs) if enough_outputs else 0.0
        )
        tactical_stability = _tactical_stability(outputs) if enough_outputs else 0.0
        strategic_stability = (0.4 * timing_stability) + (0.6 * tactical_stability)
        grounding, evidence_coverage, grounding_violations = (
            _power_spike_grounding(outputs, self.hero)
            if outputs
            else (0.0, 0.0, ["no completed generations to ground"])
        )
        curve_grounding, curve_violations = (
            _duration_curve_grounding(outputs, self.hero)
            if outputs
            else (0.0, ["no completed generations to compare with the curve"])
        )
        (
            exact_identity,
            quarter_identity,
            item_identity,
            ability_identity,
        ) = (
            _power_spike_identity(outputs, self.hero)
            if enough_outputs
            else (0.0, 0.0, 0.0, 0.0)
        )
        same_tier_item_exact = (
            _intersection_fraction(item_sets) if enough_outputs else 0.0
        )
        ability_plan_exact = (
            _intersection_fraction(ability_sets) if enough_outputs else 0.0
        )
        macro_plan_exact = _intersection_fraction(macro_sets) if enough_outputs else 0.0
        macro_lexical_overlap = (
            _pairwise_quarter_containment(macro_sets) if enough_outputs else 0.0
        )
        item_pairwise_overlap = (
            _pairwise_quarter_containment(item_sets) if enough_outputs else 0.0
        )
        ability_pairwise_overlap = (
            _pairwise_quarter_containment(ability_sets) if enough_outputs else 0.0
        )
        breakdown = {
            "completion": completion,
            "production_contract": contract,
            "per_tier_quality": tier_quality,
            "cross_tier_progression": progression,
            "power_spike_stability": strategic_stability,
            "power_spike_timing_stability": timing_stability,
            "power_spike_tactical_stability": tactical_stability,
            "power_spike_grounding": grounding,
            "power_spike_evidence_coverage": evidence_coverage,
            "power_spike_exact_identity": exact_identity,
            "power_spike_quarter_identity": quarter_identity,
            "power_spike_item_identity": item_identity,
            "power_spike_ability_identity": ability_identity,
            "duration_curve_grounding": curve_grounding,
            "curve_response_stability": float(
                enough_outputs and len(curve_responses) == 1
            ),
            "same_tier_item_stability": (
                _majority_quarter_support(item_sets) if enough_outputs else 0.0
            ),
            "ability_plan_stability": (
                _majority_quarter_support(ability_sets) if enough_outputs else 0.0
            ),
            "macro_plan_stability": (
                _macro_identity_stability(outputs, self.hero) if enough_outputs else 0.0
            ),
            "macro_plan_lexical_overlap": macro_lexical_overlap,
            "same_tier_item_pairwise_overlap": item_pairwise_overlap,
            "ability_plan_pairwise_overlap": ability_pairwise_overlap,
            "same_tier_item_exact_identity": same_tier_item_exact,
            "ability_plan_exact_identity": ability_plan_exact,
            "macro_plan_exact_identity": macro_plan_exact,
        }
        self.score_breakdown = breakdown
        scoring_fields = (
            "completion",
            "production_contract",
            "per_tier_quality",
            "cross_tier_progression",
            "power_spike_stability",
            "power_spike_grounding",
            "duration_curve_grounding",
            "curve_response_stability",
            "same_tier_item_stability",
            "ability_plan_stability",
            "macro_plan_stability",
        )
        score = min(breakdown[field] for field in scoring_fields)
        errors = [
            str(sample.get("error"))
            for sample in samples
            if isinstance(sample, dict) and sample.get("error")
        ]
        weak = [
            f"{name}={breakdown[name]:.2f}"
            for name in scoring_fields
            if breakdown[name] < 1
        ]
        identity = (
            f"exact identity={exact_identity:.2f} "
            f"(quarter={quarter_identity:.2f}, item={item_identity:.2f}, "
            f"ability={ability_identity:.2f})"
        )
        tier_details = [
            f"generation {generation}: {violation}"
            for generation, violations in enumerate(tier_violation_sets, start=1)
            for violation in violations
        ]
        progression_details = [
            f"generation {generation}: {violation}"
            for generation, violations in enumerate(
                progression_violation_sets,
                start=1,
            )
            for violation in violations
        ]
        details = [
            *grounding_violations,
            *curve_violations,
            *tier_details,
            *progression_details,
        ]
        evidence = _outcome_evidence_summary(outputs, self.hero)
        if score < self.threshold:
            reason = "Reliability shortfalls: " + ", ".join(weak)
            if details:
                reason += "; " + " | ".join(details[:4])
            if errors:
                reason += "; errors: " + " | ".join(errors)
        else:
            durations = [
                float(sample["duration_seconds"])
                for sample in samples
                if isinstance(sample, dict)
                and isinstance(sample.get("duration_seconds"), int | float)
            ]
            latency = (
                f"; latency {min(durations):.1f}-{max(durations):.1f}s"
                if durations
                else ""
            )
            variation = "; tolerated variation: " + ", ".join(weak) if weak else ""
            reason = (
                f"{len(outputs)}/{len(samples)} strategically stable generations"
                f"{latency}{variation}; {identity}"
            )
        if evidence:
            reason += "; outcome evidence: " + evidence
        return self._record(score, reason)


def production_metrics(hero: dict[str, Any]) -> list[BaseMetric]:
    """Build the complete per-generation metric set.

    Returns:
        Production contract, per-tier quality, and progression metrics.

    """
    return [
        ProductionContractMetric(hero),
        PerTierTacticalQualityMetric(hero),
        CrossTierProgressionMetric(hero),
    ]
