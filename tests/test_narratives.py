import json
from pathlib import Path

import pytest

from deadlock_build_sync.api import Patch
from deadlock_build_sync.narratives import (
    NarrativeError,
    apply_narrative,
    load_narrative_catalog,
)
from deadlock_build_sync.purchase_guide import PurchaseGuide


def write_catalog(
    path: Path,
    *,
    context_sha256: str = "a" * 64,
    narrative_basis_sha256: str = "b" * 64,
) -> None:
    path.write_text(
        json.dumps({
            "schema_version": 2,
            "prompt_version": 14,
            "patch": {"published_at": "2026-01-01T00:00:00Z"},
            "heroes": [
                {
                    "hero_id": 12,
                    "prompt_version": 14,
                    "context_sha256": context_sha256,
                    "narrative_basis_sha256": narrative_basis_sha256,
                    "build_summary": "Play around the supplied item and ability data.",
                    "quarters": {
                        "I": "Establish.",
                        "II": "Accelerate.",
                        "III": "Pressure.",
                        "IV": "Close.",
                    },
                }
            ],
        }),
        encoding="utf-8",
    )


def test_applies_matching_ai_narrative(tmp_path: Path) -> None:
    path = tmp_path / "narratives.json"
    write_catalog(path)
    catalog = load_narrative_catalog(path)
    guide = PurchaseGuide(
        12,
        "Kelvin",
        "hero_kelvin",
        {1: (), 2: (), 3: (), 4: ()},
    )
    updated = apply_narrative(
        guide,
        {
            "context_sha256": "a" * 64,
            "narrative_basis_sha256": "b" * 64,
        },
        Patch("Patch", 123, "2026-01-01T00:00:00Z"),
        catalog,
    )
    assert updated.summary.startswith("Play around")
    assert updated.tier_summaries[3] == "Pressure."


def test_accepts_narrative_as_live_analytics_advance_within_patch(
    tmp_path: Path,
) -> None:
    path = tmp_path / "narratives.json"
    write_catalog(path)
    catalog = load_narrative_catalog(path)
    guide = PurchaseGuide(
        12,
        "Kelvin",
        "hero_kelvin",
        {1: (), 2: (), 3: (), 4: ()},
    )
    updated = apply_narrative(
        guide,
        {
            "context_sha256": "c" * 64,
            "narrative_basis_sha256": "b" * 64,
        },
        Patch("Patch", 123, "2026-01-01T00:00:00Z"),
        catalog,
    )
    assert updated.tier_summaries[4] == "Close."


def test_rejects_narrative_when_tactical_basis_changes(tmp_path: Path) -> None:
    path = tmp_path / "narratives.json"
    write_catalog(path)
    catalog = load_narrative_catalog(path)
    guide = PurchaseGuide(
        12,
        "Kelvin",
        "hero_kelvin",
        {1: (), 2: (), 3: (), 4: ()},
    )

    with pytest.raises(NarrativeError, match="narrative basis changed"):
        apply_narrative(
            guide,
            {
                "context_sha256": "a" * 64,
                "narrative_basis_sha256": "c" * 64,
            },
            Patch("Patch", 123, "2026-01-01T00:00:00Z"),
            catalog,
        )


def test_rejects_outdated_tactical_prompt(tmp_path: Path) -> None:
    path = tmp_path / "narratives.json"
    write_catalog(path)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["prompt_version"] = 1
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(NarrativeError, match="outdated tactical prompt"):
        load_narrative_catalog(path)


def test_rejects_missing_narrative_basis_fingerprint(tmp_path: Path) -> None:
    path = tmp_path / "narratives.json"
    write_catalog(path)
    document = json.loads(path.read_text(encoding="utf-8"))
    del document["heroes"][0]["narrative_basis_sha256"]
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(NarrativeError, match="narrative basis fingerprint"):
        load_narrative_catalog(path)
