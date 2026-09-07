"""Frozen per-hero rank ranges and their support-driven expansion history."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .artifacts import ArtifactError
from .build_evidence_values import _required_int
from .ranks import Rank, RankDivision, RankRange, RankTier
from .value_validation import object_dict, object_rows


def ranked_cutoffs(minimum: int, maximum: int, mode: str) -> tuple[int, ...]:
    if mode not in {"auto", "off"}:
        raise ValueError("rank expansion must be auto or off")
    RankRange(badge_rank(minimum), badge_rank(maximum))
    if mode == "off" or minimum == 11:
        return (minimum,)
    lower = tuple(range((minimum // 10 - 1) * 10 + 1, 10, -10))
    return (minimum, *(lower or (11,)))


def badge_rank(badge: int) -> Rank:
    return Rank(RankTier(badge // 10), RankDivision(badge % 10))


@dataclass(frozen=True)
class HeroCohort:
    minimum_badge: int
    maximum_badge: int
    rank_expansion: str
    expansion_history: tuple[dict[str, object], ...]

    @property
    def rank_range(self) -> RankRange:
        return RankRange(badge_rank(self.minimum_badge), badge_rank(self.maximum_badge))

    def as_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["expansion_history"] = list(self.expansion_history)
        return result

    @classmethod
    def parse(cls, value: object) -> HeroCohort:
        row = object_dict(value)
        history = object_rows(row.get("expansion_history")) if row else None
        if row is None or not history:
            raise ArtifactError(
                "Hero has no rank expansion history; run refresh-evidence"
            )
        minimum = _required_int(row.get("minimum_badge"), "effective minimum badge")
        maximum = _required_int(row.get("maximum_badge"), "effective maximum badge")
        mode = str(row.get("rank_expansion"))
        start = _required_int(history[0].get("minimum_badge"), "starting minimum badge")
        try:
            cutoffs = ranked_cutoffs(start, maximum, mode)
        except ValueError as error:
            raise ArtifactError(f"Hero has an invalid rank range: {error}") from error
        if len(history) > len(cutoffs) or minimum != cutoffs[len(history) - 1]:
            raise ArtifactError("Hero has inconsistent effective ranks")
        for index, attempt in enumerate(history):
            _validate_attempt(
                attempt, cutoffs[index], maximum, last=index == len(history) - 1
            )
        return cls(minimum, maximum, mode, tuple(history))


def _validate_attempt(
    attempt: dict[str, object], minimum: int, maximum: int, *, last: bool
) -> None:
    if (
        attempt.get("minimum_badge") != minimum
        or attempt.get("maximum_badge") != maximum
    ):
        raise ArtifactError(
            "Hero rank expansion skipped a tier or changed the upper rank"
        )
    for key in (
        "discovery_rows",
        "selection_rows",
        "candidate_count",
        "discovery_owners",
        "selection_owners",
    ):
        _required_int(attempt.get(key), key)
    builds = _required_int(attempt.get("supported_builds"), "supported builds")
    if bool(builds) != last:
        raise ArtifactError("Hero expanded after support or has no supported build")
    if attempt.get("reason") != (
        "supported build available" if last else "no supported legal path"
    ):
        raise ArtifactError("Hero rank expansion has an invalid reason")
