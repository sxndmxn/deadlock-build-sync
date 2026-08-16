from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

API_BASE_URL = "https://api.deadlock-api.com"
DUCKLAKE_URL = "ducklake:https://s3-cache.deadlock-api.com/fast/db_snapshot.ducklake"
RANK_RESET_AT = datetime(2026, 7, 30, 19, 14, 37, tzinfo=UTC)
PHASES = (
    (0, 0, 540, "0–9m"),
    (1, 540, 1200, "9–20m"),
    (2, 1200, 1800, "20–30m"),
    (3, 1800, 7000, "30m+"),
)


@dataclass(frozen=True)
class Cohort:
    minimum_badge: int = 71
    maximum_badge: int = 115
    since: datetime = RANK_RESET_AT
    as_of: datetime | None = None
    match_mode: str = "Ranked"
    game_mode: str = "Normal"

    def resolved_as_of(self) -> datetime:
        return self.as_of or datetime.now(tz=UTC).replace(microsecond=0)

    def validate(self) -> None:
        if self.minimum_badge > self.maximum_badge:
            raise ValueError("minimum badge exceeds maximum badge")
        if self.since >= self.resolved_as_of():
            raise ValueError("cohort start must precede as-of timestamp")

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["since"] = self.since.isoformat()
        result["as_of"] = self.resolved_as_of().isoformat()
        return result


@dataclass(frozen=True)
class RunPaths:
    root: Path
    run: Path
    raw: Path
    data: Path
    tables: Path
    figures: Path
    api: Path

    @classmethod
    def create(cls, root: Path, run_id: str | None = None) -> RunPaths:
        identifier = run_id or datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
        run = root / "results" / identifier
        paths = cls(
            root=root,
            run=run,
            raw=run / "raw",
            data=run / "data",
            tables=run / "tables",
            figures=run / "figures",
            api=run / "raw" / "api",
        )
        for path in (paths.raw, paths.data, paths.tables, paths.figures, paths.api):
            path.mkdir(parents=True, exist_ok=True)
        return paths


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode()


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def parse_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC)
