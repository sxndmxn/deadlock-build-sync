from __future__ import annotations

import re
from dataclasses import dataclass
from enum import IntEnum
from typing import Any

from .snapshot import sha256_json


class RankTier(IntEnum):
    INITIATE = 1
    SEEKER = 2
    ACOLYTE = 3
    SENTINEL = 4
    MYSTIC = 5
    RITUALIST = 6
    EMISSARY = 7
    ORACLE = 8
    PHANTOM = 9
    ASCENDANT = 10
    ETERNUS = 11

    # Parse aliases for artifacts and command lines produced before the
    # 2026-07-30 rank rename. Numeric badge identity always wins.
    ALCHEMIST = ACOLYTE
    ARCANIST = SENTINEL
    ARCHON = EMISSARY

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
class RankCatalog:
    """Versioned numeric-tier labels from the assets response."""

    labels: dict[int, str]

    @classmethod
    def from_assets(cls, rows: list[dict[str, Any]]) -> RankCatalog:
        labels: dict[int, str] = {}
        for row in rows:
            tier = row.get("tier")
            name = row.get("name")
            if isinstance(tier, int) and isinstance(name, str) and name.strip():
                labels[tier] = name.strip()
        required = {int(tier) for tier in RankTier}
        missing = required - set(labels)
        if missing:
            formatted = ", ".join(str(tier) for tier in sorted(missing))
            raise ValueError(f"rank assets are missing tiers: {formatted}")
        return cls(labels)

    @property
    def sha256(self) -> str:
        return sha256_json(self.labels)

    def label(self, rank: Rank) -> str:
        tier = self.labels.get(int(rank.tier), rank.tier.label)
        return f"{tier} {rank.division.label}"

    def range_dict(self, rank_range: RankRange) -> dict[str, object]:
        minimum = rank_range.minimum
        maximum = rank_range.maximum
        label = (
            self.label(rank_range.minimum)
            if rank_range.minimum == rank_range.maximum
            else f"{self.label(rank_range.minimum)}–{self.label(rank_range.maximum)}"
        )
        return {
            "minimum": {
                "tier": self.labels[int(minimum.tier)].upper(),
                "division": minimum.division.label,
                "badge_id": minimum.badge_id,
                "label": self.label(minimum),
            },
            "maximum": {
                "tier": self.labels[int(maximum.tier)].upper(),
                "division": maximum.division.label,
                "badge_id": maximum.badge_id,
                "label": self.label(maximum),
            },
            "label": label,
            "labels_sha256": self.sha256,
        }

    def validate_range(self, rank_range: RankRange) -> None:
        """Ensure both numeric tier identities exist in this pinned catalog.

        Raises:
            ValueError: If either numeric rank tier is absent.

        """
        for rank in (rank_range.minimum, rank_range.maximum):
            if int(rank.tier) not in self.labels:
                raise ValueError(
                    f"rank tier {int(rank.tier)} is absent from pinned assets"
                )


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
    minimum=Rank(RankTier.EMISSARY, RankDivision.ONE),
    maximum=Rank(RankTier.ETERNUS, RankDivision.FIVE),
)
