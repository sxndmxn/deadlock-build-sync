from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from deadlock_build_sync.cache import install_guides, read_cache
from tests.cache_fixtures import (
    make_complete_guide,
    make_isolated_cache_location,
    make_snapshot_manifest,
    make_unpublished_build,
    set_deadlock_check,
)

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_install_preserves_managed_builds_for_excluded_heroes_and_user_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    location, original = make_isolated_cache_location(tmp_path)
    set_deadlock_check(monkeypatch, lambda: False)
    install_guides(
        location,
        [make_complete_guide()],
        persona="Test",
        timestamp=100,
        patch_title="Patch",
        patch_published_at="2026-01-01T00:00:00Z",
        backup_root=tmp_path / "backups",
        snapshot_manifest=make_snapshot_manifest(),
        expected_hero_ids={12},
    )
    before = read_cache(location.cache_path)
    haze = replace(
        make_complete_guide(),
        hero_id=13,
        hero_name="Haze",
        hero_class_name="hero_haze",
        policy_id="policy/haze",
    )
    result = install_guides(
        location,
        [haze],
        persona="Test",
        timestamp=101,
        patch_title="Patch",
        patch_published_at="2026-01-01T00:00:00Z",
        backup_root=tmp_path / "backups",
        snapshot_manifest=make_snapshot_manifest(),
        expected_hero_ids={13},
    )
    after = read_cache(location.cache_path)
    assert result.created == 1
    assert result.updated == 0
    assert make_unpublished_build(after)[
        : len(make_unpublished_build(before))
    ] == make_unpublished_build(before)
    for key in ("Favorites", "LastUsedBuilds", "SavedLastUsed", "UnknownFutureField"):
        assert after[key] == original[key]
    again = install_guides(
        location,
        [haze],
        persona="Test",
        timestamp=102,
        patch_title="Patch",
        patch_published_at="2026-01-01T00:00:00Z",
        backup_root=tmp_path / "backups",
        snapshot_manifest=make_snapshot_manifest(),
        expected_hero_ids={13},
    )
    assert again.created == 0
    assert again.updated == 1
    assert make_unpublished_build(read_cache(location.cache_path))[
        : len(make_unpublished_build(before))
    ] == make_unpublished_build(before)
