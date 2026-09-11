"""Check that official review files preserve the Steam presentation."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from deadlock_build_sync import cli_support
from deadlock_build_sync.cache_projection import update_managed_builds
from deadlock_build_sync.cli_build import write_build_guides
from deadlock_build_sync.guide_groups import group_guides
from deadlock_build_sync.presentation_output import (
    render_presentation_markdown,
    serialize_presentation,
)
from deadlock_build_sync.protobuf import encode_hero_build, extract_hero_build
from deadlock_build_sync.purchase_types import GuideCategory
from deadlock_build_sync.service import generate_guides
from deadlock_build_sync.value_validation import (
    require_object_dict,
    require_object_rows,
)
from tests.presentation_assertions import assert_presentation_payload
from tests.service_evidence_fixtures import make_grouped_build_evidence
from tests.service_fake_api import FakeApi, make_ability_rows, make_duration_statistics
from tests.test_protobuf import ability_guide, presentation

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("has_ability", [False, True])
def test_review_records_match_every_serialized_field(*, has_ability: bool) -> None:
    guide = ability_guide()
    item = replace(
        guide.tiers[1][0],
        annotation_text="First line.\nSecond line.",
        required_flex_slots=0,
        sell_priority=2,
        imbue_target_ability_id=10,
    )
    guide = replace(
        guide,
        categories=(
            GuideCategory("CORE", (item,), "Core description."),
            GuideCategory("TIER 4", (), optional=True, compact=True),
        ),
        ability_path=guide.ability_path if has_ability else None,
    )
    official = presentation(guide)
    record = serialize_presentation(official)
    payload = encode_hero_build(official, build_id=2, account_id=3, timestamp=4)
    assert_presentation_payload(payload, record)
    markdown = render_presentation_markdown(official)
    assert markdown.startswith(f"# {official.name}\n")
    assert "## CORE" in markdown and "## TIER 4" in markdown
    assert "No items." in markdown
    assert "Required flex slots: 0." in markdown
    assert "Sell priority: 2." in markdown and "Imbue ability ID: 10." in markdown
    assert "        First line.\n        Second line." in markdown
    assert all(
        f"    {line}" in markdown for line in official.description.splitlines() if line
    )


def test_build_files_match_preview_and_cache_projection(tmp_path: Path) -> None:
    api = FakeApi(
        ability_rows=make_ability_rows(), duration_points=make_duration_statistics()
    )
    generated = generate_guides(
        api,
        build_evidence=make_grouped_build_evidence(api),
        account_id=0,
        hero_query="Kelvin",
        all_heroes=False,
    )
    guides = group_guides(generated.guides, generated.guide_groups)
    write_build_guides(tmp_path, guides, generated)
    output = tmp_path / "builds" / generated.manifest.snapshot_id
    records = require_object_rows(
        require_object_dict(json.loads((output / "guides.json").read_text()))["guides"]
    )
    root: dict[str, object] = {"Unpublished": []}
    projected, _, created, updated, _ = update_managed_builds(
        root,
        guides,
        account_id=321,
        persona=generated.persona,
        timestamp=100,
        patch_title=generated.patch.title,
        patch_published_at=generated.patch.published_at,
        rank_range=generated.rank_range,
    )
    assert root == {"Unpublished": []}
    assert created == len(guides) and updated == 0
    wrappers = projected["Unpublished"]
    assert isinstance(wrappers, list)
    for guide, record, wrapper in zip(guides, records, wrappers, strict=True):
        content = require_object_dict(
            json.loads((output / str(record["steam_json"])).read_text())
        )
        assert content == record["steam_build"]
        assert content["categories"] == record["steam_categories"]
        assert (
            content
            == cli_support._describe_preview_guide(guide, generated, account_id=321)[
                "steam_build"
            ]
        )
        assert (
            output / str(record["markdown"])
        ).read_text() == cli_support._render_preview_guide(guide, generated)
        assert "Choice details" in cli_support._render_preview_guide(
            guide, generated, details=True
        )
        assert isinstance(wrapper, bytes)
        assert_presentation_payload(extract_hero_build(wrapper), content)
