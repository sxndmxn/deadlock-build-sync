import pytest

from deadlock_build_sync.api import HeroDurationStat
from deadlock_build_sync.power_curve import (
    summarize_duration_curve,
    summarize_duration_distribution,
)


def curve(*wins: int) -> tuple[HeroDurationStat, ...]:
    labels = ("<25m", "25–30m", "30–35m", "35–40m", "40–45m", "45–50m", "50m+")
    return tuple(
        HeroDurationStat(label, index * 300, (index + 1) * 300, win, 100 - win, 100)
        for index, (label, win) in enumerate(zip(labels, wins, strict=True))
    )


def test_identifies_late_scaling_curve() -> None:
    summary = summarize_duration_curve(curve(46, 47, 49, 50, 51, 54, 56))

    assert summary is not None
    assert summary["shape"] == "LATE_SCALING"
    assert summary["strongest_phase"] == "LATE (45m+)"
    assert summary["early_to_late_delta_percentage_points"] == 8.5
    assert summary["overall"]["matches"] == 700
    assert summary["overall"]["raw_win_rate"] == pytest.approx(0.504286)


def test_identifies_midgame_peak() -> None:
    summary = summarize_duration_curve(curve(48, 49, 54, 55, 54, 49, 48))

    assert summary is not None
    assert summary["shape"] == "MIDGAME_PEAK"


def test_rejects_incomplete_curve() -> None:
    assert summarize_duration_curve(curve(50, 51, 52, 53, 54, 55, 56)[:4]) is None


def test_rejects_curve_with_an_interior_bucket_missing() -> None:
    points = curve(40, 80, 80, 80, 20, 20, 20)

    assert summarize_duration_curve(points[:1] + points[2:]) is None


def test_duration_distribution_exposes_rare_tail() -> None:
    points = curve(50, 51, 52, 53, 54, 55, 56)
    curves = {
        1: tuple(
            HeroDurationStat(
                point.label,
                point.min_duration_s,
                point.max_duration_s,
                point.wins,
                point.losses,
                10 if point.label == "50m+" else 100,
            )
            for point in points
        )
    }

    distribution = summarize_duration_distribution(curves)

    assert distribution["50m+"]["approximate_games"] == 1
    assert distribution["50m+"]["tracked_game_share"] < 0.02
