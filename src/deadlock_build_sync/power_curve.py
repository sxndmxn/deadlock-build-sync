from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .api import HERO_DURATION_BUCKETS

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .api import HeroDurationStat

DURATION_BUCKET_LABELS = tuple(bucket[0] for bucket in HERO_DURATION_BUCKETS)


@dataclass(frozen=True)
class DurationPhase:
    label: str
    wins: int
    matches: int

    @property
    def win_rate(self) -> float:
        return self.wins / self.matches if self.matches else 0.0


def _phase(label: str, points: Iterable[HeroDurationStat]) -> DurationPhase:
    selected = tuple(points)
    return DurationPhase(
        label=label,
        wins=sum(point.wins for point in selected),
        matches=sum(point.matches for point in selected),
    )


def _ordered_duration_points(
    points: tuple[HeroDurationStat, ...],
) -> tuple[HeroDurationStat, ...] | None:
    points_by_label = {point.label: point for point in points}
    if len(points) != len(DURATION_BUCKET_LABELS) or set(points_by_label) != set(
        DURATION_BUCKET_LABELS
    ):
        return None
    return tuple(points_by_label[label] for label in DURATION_BUCKET_LABELS)


def summarize_duration_distribution(
    curves: dict[int, tuple[HeroDurationStat, ...]],
) -> dict[str, dict[str, float | int]]:
    hero_slots: Counter[str] = Counter()
    for points in curves.values():
        for point in points:
            hero_slots[point.label] += point.matches
    total_slots = sum(hero_slots.values())
    if total_slots == 0:
        return {}
    return {
        label: {
            "hero_slots": slots,
            "approximate_games": round(slots / 12),
            "tracked_game_share": round(slots / total_slots, 6),
        }
        for label, slots in hero_slots.items()
    }


def summarize_duration_curve(
    points: tuple[HeroDurationStat, ...],
    distribution: dict[str, dict[str, float | int]] | None = None,
) -> dict[str, Any] | None:
    ordered_points = _ordered_duration_points(points)
    if ordered_points is None:
        return None

    phases = (
        _phase("EARLY (<30m)", ordered_points[:2]),
        _phase("MID (30–45m)", ordered_points[2:5]),
        _phase("LATE (45m+)", ordered_points[5:]),
    )
    if any(phase.matches < 50 for phase in phases):
        return None

    strongest_phase = max(phases, key=lambda phase: phase.win_rate)
    weakest_phase = min(phases, key=lambda phase: phase.win_rate)
    spread = strongest_phase.win_rate - weakest_phase.win_rate
    early, middle, late = phases

    if spread < 0.015:
        shape = "STABLE"
    elif (
        middle.win_rate >= early.win_rate + 0.01
        and middle.win_rate >= late.win_rate + 0.01
    ):
        shape = "MIDGAME_PEAK"
    elif late.win_rate >= early.win_rate + 0.02:
        shape = "LATE_SCALING"
    elif early.win_rate >= late.win_rate + 0.02:
        shape = "EARLY_CLOSER"
    else:
        shape = "MIXED"

    distribution = distribution or summarize_duration_distribution({0: ordered_points})
    representative_points = tuple(
        point
        for point in ordered_points
        if float(distribution.get(point.label, {}).get("tracked_game_share") or 0)
        >= 0.03
    )
    if not representative_points:
        representative_points = ordered_points
    strongest_bucket = max(representative_points, key=lambda point: point.win_rate)
    weakest_bucket = min(representative_points, key=lambda point: point.win_rate)
    late_share = sum(
        float(distribution.get(point.label, {}).get("tracked_game_share") or 0)
        for point in ordered_points[5:]
    )
    tail_share = float(
        distribution.get(DURATION_BUCKET_LABELS[-1], {}).get("tracked_game_share") or 0
    )
    return {
        "shape": shape,
        "strongest_phase": strongest_phase.label,
        "weakest_phase": weakest_phase.label,
        "early_to_late_delta_percentage_points": round(
            100 * (late.win_rate - early.win_rate),
            2,
        ),
        "strongest_bucket": strongest_bucket.label,
        "weakest_bucket": weakest_bucket.label,
        "overall": {
            "raw_win_rate": round(_phase("OVERALL", ordered_points).win_rate, 6),
            "matches": sum(point.matches for point in ordered_points),
        },
        "late_phase_tracked_game_share": round(late_share, 6),
        "fifty_plus_tracked_game_share": round(tail_share, 6),
        "phases": [
            {
                "label": phase.label,
                "raw_win_rate": round(phase.win_rate, 6),
                "matches": phase.matches,
            }
            for phase in phases
        ],
        "buckets": [
            {
                "label": point.label,
                "min_duration_s": point.min_duration_s,
                "max_duration_s": point.max_duration_s,
                "raw_win_rate": round(point.win_rate, 6),
                "matches": point.matches,
                "population": distribution.get(point.label, {}),
            }
            for point in ordered_points
        ],
        "interpretation": (
            "Duration buckets are outcome-conditioned observational evidence. "
            "The 50m+ bucket is a rare tail and cannot define the curve by itself. "
            "Use weighted broad phases and adjacent-bucket support; do not claim "
            "that game length or an item causes the win rate."
        ),
    }
