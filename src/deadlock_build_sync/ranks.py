from __future__ import annotations

import re
from dataclasses import dataclass
from enum import IntEnum


class RankTier(IntEnum):
    INITIATE = 1
    SEEKER = 2
    ALCHEMIST = 3
    ARCANIST = 4
    RITUALIST = 5
    EMISSARY = 6
    ARCHON = 7
    ORACLE = 8
    PHANTOM = 9
    ASCENDANT = 10
    ETERNUS = 11

    @property
    def label(self) -> str:
        return self.name.title()


class RankDivision(IntEnum):
    ONE = 1
    TWO = 2
    THREE = 3
    FOUR = 4
    FIVE = 5
    SIX = 6

    @property
    def label(self) -> str:
        return ("I", "II", "III", "IV", "V", "VI")[int(self) - 1]

    @classmethod
    def parse(cls, value: str) -> RankDivision:
        normalized = value.strip().upper()
        if normalized.isdigit():
            return cls(int(normalized))
        if normalized in cls.__members__:
            return cls[normalized]
        roman_divisions = ("I", "II", "III", "IV", "V", "VI")
        return cls(roman_divisions.index(normalized) + 1)


@dataclass(frozen=True)
class Rank:
    tier: RankTier
    division: RankDivision

    @property
    def badge_id(self) -> int:
        return int(self.tier) * 10 + int(self.division)

    @property
    def label(self) -> str:
        return f"{self.tier.label} {self.division.label}"

    @property
    def slug(self) -> str:
        return f"{self.tier.name.casefold()}-{self.division.label.casefold()}"

    @classmethod
    def parse(cls, value: str) -> Rank:
        normalized = re.sub(r"[\s_]+", "-", value.strip()).casefold()
        tier_name, separator, division_name = normalized.rpartition("-")
        if not separator:
            raise ValueError("rank must include a tier and division")
        try:
            tier = RankTier[tier_name.upper()]
            division = RankDivision.parse(division_name)
        except (KeyError, ValueError) as error:
            raise ValueError(f"unknown Deadlock rank: {value}") from error
        return cls(tier, division)


@dataclass(frozen=True)
class RankRange:
    minimum: Rank
    maximum: Rank

    def __post_init__(self) -> None:
        """Validate boundary ordering.

        Raises:
            ValueError: If the minimum rank exceeds the maximum rank.

        """
        if self.minimum.badge_id > self.maximum.badge_id:
            raise ValueError(
                f"minimum rank {self.minimum.label} exceeds "
                f"maximum rank {self.maximum.label}"
            )

    @property
    def label(self) -> str:
        if self.minimum == self.maximum:
            return self.minimum.label
        return f"{self.minimum.label}–{self.maximum.label}"

    @property
    def api_parameters(self) -> dict[str, int]:
        return {
            "min_average_badge": self.minimum.badge_id,
            "max_average_badge": self.maximum.badge_id,
        }

    def as_dict(self) -> dict[str, object]:
        return {
            "minimum": {
                "tier": self.minimum.tier.name,
                "division": self.minimum.division.label,
                "badge_id": self.minimum.badge_id,
                "label": self.minimum.label,
            },
            "maximum": {
                "tier": self.maximum.tier.name,
                "division": self.maximum.division.label,
                "badge_id": self.maximum.badge_id,
                "label": self.maximum.label,
            },
            "label": self.label,
        }


DEFAULT_RANK_RANGE = RankRange(
    minimum=Rank(RankTier.PHANTOM, RankDivision.ONE),
    maximum=Rank(RankTier.ETERNUS, RankDivision.SIX),
)
