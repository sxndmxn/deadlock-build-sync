"""Value objects and parsing helpers for the public API client."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from .snapshot import canonical_json, sha256_json
from .value_validation import integer, object_dict

DEFAULT_API_BASE_URL = "https://api.deadlock-api.com"
GAME_MODE = "normal"
_STEAM_CDN_HOST_PATTERN = re.compile(
    r"(?<=://)(clan|shared)\.(?:akamai|fastly)\.steamstatic\.com",
    re.IGNORECASE,
)


class ApiError(RuntimeError):
    """Raised when deadlock-api.com returns invalid or unavailable data."""


@dataclass(frozen=True)
class Patch:
    title: str
    start_timestamp: int
    published_at: str
    source: str = "unknown"
    guid: str = "unknown"
    link: str = ""
    content_sha256: str = ""

    @property
    def identity(self) -> str:
        return sha256_json({
            "source": self.source,
            "guid": self.guid,
            "published_at": self.published_at,
            "link": self.link,
            "content_sha256": self.content_sha256,
        })

    def as_dict(self) -> dict[str, object]:
        return {
            "identity": self.identity,
            "title": self.title,
            "start_timestamp": self.start_timestamp,
            "published_at": self.published_at,
            "source": self.source,
            "guid": self.guid,
            "link": self.link,
            "content_sha256": self.content_sha256,
        }


@dataclass(frozen=True)
class HeroDurationStat:
    label: str
    min_duration_s: int
    max_duration_s: int
    wins: int
    losses: int
    matches: int

    @property
    def win_rate(self) -> float:
        return self.wins / self.matches if self.matches else 0.0


# Domain intervals exclude the upper bound. The API includes both integer bounds.
# Send max_duration_s - 1 as the API upper bound.
HERO_DURATION_BUCKETS = (
    ("<25m", 0, 1500),
    ("25–30m", 1500, 1800),
    ("30–35m", 1800, 2100),
    ("35–40m", 2100, 2400),
    ("40–45m", 2400, 2700),
    ("45–50m", 2700, 3000),
    ("50m+", 3000, 7000),
)
MIN_HERO_DURATION_MATCHES = 20


def parse_duration_statistics(
    row: object,
    label: str,
    minimum: int,
    maximum_exclusive: int,
) -> tuple[int, HeroDurationStat] | None:
    data = object_dict(row)
    if data is None:
        return None
    hero_id = data.get("hero_id")
    if not isinstance(hero_id, int):
        return None
    matches = integer(data.get("matches"), default=0)
    wins = integer(data.get("wins"), default=0)
    losses = integer(data.get("losses"), default=0)
    if matches < MIN_HERO_DURATION_MATCHES or wins + losses != matches:
        return None
    return hero_id, HeroDurationStat(
        label=label,
        min_duration_s=minimum,
        max_duration_s=maximum_exclusive,
        wins=wins,
        losses=losses,
        matches=matches,
    )


def parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ApiError(f"invalid current patch timestamp: {value}") from error
    return parsed.replace(tzinfo=parsed.tzinfo or UTC)


def normalize_patch_guid(value: object) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, (dict, list)):
        return canonical_json(value).decode()
    return "unknown"


def normalize_patch_content(value: object) -> object:
    if isinstance(value, str):
        return _STEAM_CDN_HOST_PATTERN.sub(r"\1.cdn.steamstatic.com", value)
    if isinstance(value, list):
        return [normalize_patch_content(nested) for nested in value]
    if isinstance(value, dict):
        return {
            str(key): normalize_patch_content(nested) for key, nested in value.items()
        }
    return value


def calculate_patch_content_sha256(value: object) -> str:
    """Hash patch content after normalizing Steam CDN host names.

    Returns:
        A digest that changes when the patch notes change.

    """
    return hashlib.sha256(canonical_json(normalize_patch_content(value))).hexdigest()
