from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from .api import Patch
    from .purchase_guide import PurchaseGuide

NARRATIVE_SCHEMA_VERSION = 2
NARRATIVE_PROMPT_VERSION = 14
DEFAULT_KIT_MODEL = "gpt-5.6-luna"
DEFAULT_SYNTHESIS_MODEL = "gpt-5.6-sol"
TIER_LABELS = {1: "I", 2: "II", 3: "III", 4: "IV"}


class NarrativeError(RuntimeError):
    """Raised when an AI-authored narrative artifact is invalid or stale."""


@dataclass(frozen=True)
class NarrativeCatalog:
    patch_published_at: str
    heroes: dict[int, dict[str, Any]]


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _validate_fingerprints(path: Path, entry: dict[str, Any]) -> None:
    if not _is_sha256(entry.get("context_sha256")):
        raise NarrativeError(
            f"{path} contains a hero without a valid context fingerprint"
        )
    if not _is_sha256(entry.get("narrative_basis_sha256")):
        raise NarrativeError(
            f"{path} contains a hero without a valid narrative basis fingerprint"
        )


def load_narrative_catalog(path: Path) -> NarrativeCatalog:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise NarrativeError(
            f"could not read narrative artifact {path}: {error}"
        ) from error
    if (
        not isinstance(data, dict)
        or data.get("schema_version") != NARRATIVE_SCHEMA_VERSION
    ):
        raise NarrativeError(
            f"{path} is not a supported narrative artifact; regenerate it"
        )
    if data.get("prompt_version") != NARRATIVE_PROMPT_VERSION:
        raise NarrativeError(f"{path} was generated with an outdated tactical prompt")
    patch = data.get("patch")
    entries = data.get("heroes")
    if not isinstance(patch, dict) or not isinstance(entries, list):
        raise NarrativeError(f"{path} is missing patch or hero narrative data")
    heroes: dict[int, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("hero_id"), int):
            raise NarrativeError(f"{path} contains an invalid hero narrative")
        if entry.get("prompt_version") != NARRATIVE_PROMPT_VERSION:
            raise NarrativeError(
                f"{path} contains a hero generated with an outdated tactical prompt"
            )
        _validate_fingerprints(path, entry)
        hero_id = int(entry["hero_id"])
        if hero_id in heroes:
            raise NarrativeError(f"{path} contains duplicate hero {hero_id}")
        heroes[hero_id] = entry
    return NarrativeCatalog(str(patch.get("published_at") or ""), heroes)


def apply_narrative(
    guide: PurchaseGuide,
    context: dict[str, Any],
    patch: Patch,
    catalog: NarrativeCatalog,
) -> PurchaseGuide:
    if catalog.patch_published_at != patch.published_at:
        raise NarrativeError(
            "narrative artifact patch does not match the live analytics patch"
        )
    entry = catalog.heroes.get(guide.hero_id)
    if entry is None:
        raise NarrativeError(f"narrative artifact is missing {guide.hero_name}")
    if entry.get("narrative_basis_sha256") != context.get("narrative_basis_sha256"):
        raise NarrativeError(
            f"narrative basis changed for {guide.hero_name}; regenerate the artifact"
        )
    summary = entry.get("build_summary")
    quarters = entry.get("quarters")
    if (
        not isinstance(summary, str)
        or not summary.strip()
        or not isinstance(quarters, dict)
    ):
        raise NarrativeError(f"narrative for {guide.hero_name} is incomplete")
    tier_summaries = {}
    for tier, label in TIER_LABELS.items():
        value = quarters.get(label)
        if not isinstance(value, str) or not value.strip():
            raise NarrativeError(
                f"narrative for {guide.hero_name} is missing quarter {label}"
            )
        tier_summaries[tier] = value.strip()
    return replace(
        guide,
        summary=summary.strip(),
        tier_summaries=tier_summaries,
    )
