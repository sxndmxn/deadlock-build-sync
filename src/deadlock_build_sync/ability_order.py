from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import cache
from typing import Any

COMPLETE_ABILITY_PATH_LENGTH = 16
LOW_ABILITY_DECISION_SUPPORT = 20


@dataclass(frozen=True)
class AbilityPath:
    """Default Steam projection selected from reached-state decisions."""

    ability_ids: tuple[int, ...]
    matches: int
    wins: int
    losses: int
    cohort_matches: int
    complete_path_matches: int = 0
    decision_support: tuple[int, ...] = ()
    selection: str = "MOST_SUPPORTED_LEGAL_STATE"
    filter_item_ids: tuple[int, ...] = ()

    @property
    def final_branch_support_share(self) -> float:
        """Final-branch support divided by valid telemetry appearances.

        Returns:
            Selected final decision support divided by valid telemetry appearances.

        """
        return self.matches / self.cohort_matches if self.cohort_matches else 0.0

    @property
    def observed_final_branch_outcome_rate(self) -> float:
        """Descriptive outcome rate for the final continuation.

        Returns:
            Raw wins divided by support.

        """
        return self.wins / self.matches if self.matches else 0.0

    @property
    def minimum_decision_support(self) -> int:
        """Support at the weakest reached decision in the projection."""
        return min(self.decision_support, default=self.matches)

    @property
    def annotation(self) -> str:
        prefix = (
            "Low-support tail • "
            if self.minimum_decision_support < LOW_ABILITY_DECISION_SUPPORT
            else ""
        )
        return (
            f"{prefix}State-composed observed default • tail support "
            f"n={self.matches:,} • observational."
        )


def _valid_path(value: object) -> tuple[int, ...] | None:
    if not isinstance(value, list) or not value or len(value) > 16:
        return None
    path: list[int] = []
    for ability_id in value:
        if not isinstance(ability_id, int):
            return None
        path.append(ability_id)
    if len(set(path)) > 4 or any(count > 4 for count in Counter(path).values()):
        return None
    return tuple(path)


def _ability_state(path: tuple[int, ...]) -> tuple[tuple[int, int], ...]:
    return tuple(sorted(Counter(path).items()))


type _AbilityObservation = tuple[tuple[int, ...], int, int, int]
type _DecisionCounts = dict[
    tuple[int, tuple[tuple[int, int], ...]],
    dict[int, tuple[int, int, int]],
]


def _valid_observations(rows: list[dict[str, Any]]) -> list[_AbilityObservation]:
    valid: list[_AbilityObservation] = []
    for row in rows:
        path = _valid_path(row.get("abilities"))
        matches = int(row.get("matches") or 0)
        wins = int(row.get("wins") or 0)
        losses = int(row.get("losses") or 0)
        if (
            path is not None
            and matches > 0
            and wins >= 0
            and losses >= 0
            and wins + losses == matches
        ):
            valid.append((path, matches, wins, losses))
    return valid


def _decision_counts(valid: list[_AbilityObservation]) -> _DecisionCounts:
    decisions: _DecisionCounts = defaultdict(dict)
    for path, matches, wins, losses in valid:
        for index, ability_id in enumerate(path):
            state = index, _ability_state(path[:index])
            prior = decisions[state].get(ability_id, (0, 0, 0))
            decisions[state][ability_id] = (
                prior[0] + matches,
                prior[1] + wins,
                prior[2] + losses,
            )
    return decisions


def _compose_default_path(
    decisions: _DecisionCounts,
) -> tuple[tuple[int, ...], tuple[int, ...], tuple[int, int, int]] | None:
    @cache
    def suffix(
        position: int,
        state: tuple[tuple[int, int], ...],
    ) -> tuple[tuple[int, ...], tuple[int, ...], tuple[int, int, int]] | None:
        counts_by_ability = dict(state)
        if position == COMPLETE_ABILITY_PATH_LENGTH:
            if len(counts_by_ability) == 4 and all(
                count == 4 for count in counts_by_ability.values()
            ):
                return (), (), (0, 0, 0)
            return None
        candidates = decisions.get((position, state), {})
        eligible = sorted(
            (
                (ability_id, counts)
                for ability_id, counts in candidates.items()
                if counts_by_ability.get(ability_id, 0) < 4
            ),
            key=lambda candidate: (-candidate[1][0], candidate[0]),
        )
        for ability_id, observation_counts in eligible:
            next_counts = dict(counts_by_ability)
            next_counts[ability_id] = next_counts.get(ability_id, 0) + 1
            continuation = suffix(position + 1, tuple(sorted(next_counts.items())))
            if continuation is None:
                continue
            path, support, tail_counts = continuation
            return (
                (ability_id, *path),
                (observation_counts[0], *support),
                tail_counts if path else observation_counts,
            )
        return None

    return suffix(0, ())


def select_ability_path(
    rows: list[dict[str, Any]],
    *,
    filter_item_ids: tuple[int, ...] = (),
) -> AbilityPath | None:
    """Select a complete default from reached legal ability-rank states.

    Returns:
        A complete legal-count projection using all observations that reached each state.

    """
    valid = _valid_observations(rows)
    cohort_matches = sum(matches for _, matches, _, _ in valid)
    if cohort_matches == 0:
        return None
    complete_path_matches = sum(
        matches
        for path, matches, _, _ in valid
        if len(path) == COMPLETE_ABILITY_PATH_LENGTH
    )
    composed = _compose_default_path(_decision_counts(valid))
    if composed is None:
        return None
    selected, support, final_counts = composed
    return AbilityPath(
        ability_ids=selected,
        matches=final_counts[0],
        wins=final_counts[1],
        losses=final_counts[2],
        cohort_matches=cohort_matches,
        complete_path_matches=complete_path_matches,
        decision_support=support,
        selection=(
            "MOST_SUPPORTED_LEGAL_STATE_ITEM_FILTERED"
            if filter_item_ids
            else "MOST_SUPPORTED_LEGAL_STATE"
        ),
        filter_item_ids=filter_item_ids,
    )
