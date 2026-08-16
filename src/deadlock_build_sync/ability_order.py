from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
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


def select_ability_path(rows: list[dict[str, Any]]) -> AbilityPath | None:
    """Select a complete default from reached legal ability-rank states.

    Returns:
        A complete legal-count projection using all observations that reached each state.

    """
    valid: list[tuple[tuple[int, ...], int, int, int]] = []
    for row in rows:
        path = _valid_path(row.get("abilities"))
        matches = int(row.get("matches") or 0)
        wins = int(row.get("wins") or 0)
        losses = int(row.get("losses") or 0)
        if (
            path is None
            or matches <= 0
            or wins < 0
            or losses < 0
            or wins + losses != matches
        ):
            continue
        valid.append((path, matches, wins, losses))
    cohort_matches = sum(matches for _, matches, _, _ in valid)
    if cohort_matches == 0:
        return None
    complete_path_matches = sum(
        matches
        for path, matches, _, _ in valid
        if len(path) == COMPLETE_ABILITY_PATH_LENGTH
    )
    decisions: dict[
        tuple[int, tuple[tuple[int, int], ...]],
        dict[int, tuple[int, int, int]],
    ] = defaultdict(dict)
    for path, matches, wins, losses in valid:
        for index, ability_id in enumerate(path):
            state = index, _ability_state(path[:index])
            prior = decisions[state].get(ability_id, (0, 0, 0))
            decisions[state][ability_id] = (
                prior[0] + matches,
                prior[1] + wins,
                prior[2] + losses,
            )

    selected: list[int] = []
    support: list[int] = []
    final_counts = (0, 0, 0)
    for position in range(COMPLETE_ABILITY_PATH_LENGTH):
        candidates = decisions.get((position, _ability_state(tuple(selected))), {})
        eligible = [
            (ability_id, counts)
            for ability_id, counts in candidates.items()
            if selected.count(ability_id) < 4
        ]
        if not eligible:
            return None
        ability_id, final_counts = min(
            eligible,
            key=lambda candidate: (-candidate[1][0], candidate[0]),
        )
        selected.append(ability_id)
        support.append(final_counts[0])
    counts = Counter(selected)
    if len(counts) != 4 or any(count != 4 for count in counts.values()):
        return None
    return AbilityPath(
        ability_ids=tuple(selected),
        matches=final_counts[0],
        wins=final_counts[1],
        losses=final_counts[2],
        cohort_matches=cohort_matches,
        complete_path_matches=complete_path_matches,
        decision_support=tuple(support),
    )
