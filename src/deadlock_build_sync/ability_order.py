from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

COMPLETE_ABILITY_PATH_LENGTH = 16
MIN_ABILITY_PATH_MATCHES = 20


@dataclass(frozen=True)
class AbilityPath:
    ability_ids: tuple[int, ...]
    matches: int
    wins: int
    losses: int
    cohort_matches: int

    @property
    def pick_rate(self) -> float:
        return self.matches / self.cohort_matches if self.cohort_matches else 0.0

    @property
    def win_rate(self) -> float:
        return self.wins / self.matches if self.matches else 0.0

    @property
    def annotation(self) -> str:
        return (
            f"Path pick {self.pick_rate * 100:.1f}% | "
            f"Raw WR {self.win_rate * 100:.1f}% | {self.matches:,} matches"
        )


def select_ability_path(rows: list[dict[str, Any]]) -> AbilityPath | None:
    complete: list[tuple[tuple[int, ...], int, int, int]] = []
    for row in rows:
        abilities = row.get("abilities")
        if (
            not isinstance(abilities, list)
            or len(abilities) != COMPLETE_ABILITY_PATH_LENGTH
            or not all(isinstance(ability_id, int) for ability_id in abilities)
        ):
            continue
        ability_counts = Counter(abilities)
        if len(ability_counts) != 4 or any(
            count != 4 for count in ability_counts.values()
        ):
            continue
        matches = int(row.get("matches") or 0)
        wins = int(row.get("wins") or 0)
        losses = int(row.get("losses") or 0)
        if matches < MIN_ABILITY_PATH_MATCHES or wins < 0 or losses < 0:
            continue
        complete.append((tuple(abilities), matches, wins, losses))

    cohort_matches = sum(matches for _, matches, _, _ in complete)
    if cohort_matches == 0:
        return None

    ability_ids, matches, wins, losses = min(
        complete,
        key=lambda path: (
            -path[1],
            -(path[2] / path[1]),
            path[0],
        ),
    )
    return AbilityPath(
        ability_ids=ability_ids,
        matches=matches,
        wins=wins,
        losses=losses,
        cohort_matches=cohort_matches,
    )
