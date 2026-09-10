"""Guide and catalog inputs for narrative tests."""

import json
from pathlib import Path

from deadlock_build_sync.api import Patch
from deadlock_build_sync.narratives import (
    NARRATIVE_GENERATOR_VERSION,
    NARRATIVE_SCHEMA_VERSION,
)
from deadlock_build_sync.purchase_guide import GuideCategory, GuideItem, PurchaseGuide

SNAPSHOT_ID = "1" * 64
POLICY_ID = "2" * 64
CONTEXT_ID = "3" * 64
BASIS_ID = "4" * 64
SOURCE_ID = "5" * 64
PATCH = Patch("Patch", 123, "2026-01-01T00:00:00Z")
DESCRIPTION = (
    "Control committed fights with Kelvin's space denial while the supported "
    "CORE path keeps steady pressure available between protective rotations."
)


def make_narrative_guide() -> PurchaseGuide:
    core = GuideItem(101, "Frost Core", 1, 100, 0.5, 0.4, 1.0, ())
    option = GuideItem(102, "Barrier", 1, 80, 0.5, 0.4, 0.8, ())
    return PurchaseGuide(
        12,
        "Kelvin",
        "hero_kelvin",
        {1: (core, option), 2: (), 3: (), 4: ()},
        categories=(
            GuideCategory("CORE ITEMS", (core,), "fixed core text"),
            GuideCategory("TIER 1", (option,), "fixed tier text", optional=True),
        ),
        snapshot_id=SNAPSHOT_ID,
        policy_id=POLICY_ID,
        client_version=123,
        match_mode="ranked",
    )


def write_catalog(path: Path, **overrides: object) -> None:
    entry = {
        "hero_id": 12,
        "path_id": "default",
        "generator_version": NARRATIVE_GENERATOR_VERSION,
        "snapshot_id": SNAPSHOT_ID,
        "policy_id": POLICY_ID,
        "context_sha256": CONTEXT_ID,
        "narrative_basis_sha256": BASIS_ID,
        "build_description": DESCRIPTION,
    }
    document = {
        "schema_version": NARRATIVE_SCHEMA_VERSION,
        "generator_version": NARRATIVE_GENERATOR_VERSION,
        "source_context_sha256": SOURCE_ID,
        "snapshot_id": SNAPSHOT_ID,
        "patch": PATCH.as_dict(),
        "cohort": {
            "client_version": 123,
            "match_mode": "ranked",
            "game_mode": "normal",
        },
        "requested_hero_ids": [12],
        "exclusions": [],
        "heroes": [entry],
        **overrides,
    }
    path.write_text(json.dumps(document), encoding="utf-8")
