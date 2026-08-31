from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

import deadlock_build_sync.cache_install as cache_install_module
import deadlock_build_sync.cache_storage as cache_storage_module
from deadlock_build_sync.cache import (
    CacheError,
    install_guides,
    read_cache,
)
from tests.cache_fixtures import (
    complete_guide,
    install_complete,
    isolated_location,
    set_deadlock_check,
    snapshot_manifest,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_install_refuses_if_deadlock_starts_at_mutation_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    location, original = isolated_location(tmp_path)
    states = iter((False, True))
    set_deadlock_check(monkeypatch, lambda: next(states))

    with pytest.raises(CacheError, match="started before replacement"):
        install_complete(location, tmp_path / "state")

    assert read_cache(location.cache_path) == original


def test_install_restores_after_directory_fsync_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    location, original = isolated_location(tmp_path)
    set_deadlock_check(monkeypatch, lambda: False)
    real_fsync_directory = cache_storage_module._fsync_directory
    target_fsync_calls = 0

    def inject_failure(path: Path) -> None:
        nonlocal target_fsync_calls
        if path == location.cache_path.parent:
            target_fsync_calls += 1
        if path == location.cache_path.parent and target_fsync_calls == 1:
            raise OSError("injected target-directory fsync failure")
        real_fsync_directory(path)

    monkeypatch.setattr(cache_storage_module, "_fsync_directory", inject_failure)

    with pytest.raises(CacheError, match="original cache was restored"):
        install_complete(location, tmp_path / "state")

    assert read_cache(location.cache_path) == original


def test_out_of_scope_corruption_is_detected_and_restored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    location, original = isolated_location(tmp_path)
    set_deadlock_check(monkeypatch, lambda: False)
    real_read_cache = cache_storage_module.read_cache
    calls = 0

    def corrupt_candidate(path: Path) -> dict[str, object]:
        nonlocal calls
        calls += 1
        root = real_read_cache(path)
        if calls == 2:
            root["Favorites"] = [b"corrupted"]
        return root

    monkeypatch.setattr(cache_storage_module, "read_cache", corrupt_candidate)

    with pytest.raises(CacheError, match="out-of-scope"):
        install_complete(location, tmp_path / "state")

    assert real_read_cache(location.cache_path) == original


def test_all_hero_installation_refuses_missing_roster_member(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    location, original = isolated_location(tmp_path)
    set_deadlock_check(monkeypatch, lambda: False)
    guides = [complete_guide()]
    manifest = snapshot_manifest()

    with pytest.raises(CacheError, match="coverage mismatch"):
        install_guides(
            location,
            guides,
            persona="XMLJDX",
            timestamp=100,
            patch_title="Patch",
            patch_published_at="2026-01-01T00:00:00Z",
            backup_root=tmp_path / "state",
            snapshot_manifest=manifest,
            expected_hero_ids={12, 13},
        )

    assert read_cache(location.cache_path) == original
    assert not (tmp_path / "state").exists()


def test_double_failure_reports_recoverable_backup_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    location, _ = isolated_location(tmp_path)
    states = iter((False, True))
    set_deadlock_check(monkeypatch, lambda: next(states))
    monkeypatch.setattr(
        cache_install_module,
        "_restore_cache_file",
        lambda _source, _destination: (_ for _ in ()).throw(OSError("restore failed")),
    )

    with pytest.raises(CacheError, match=r"automatic restore failed.*backup is at"):
        install_complete(location, tmp_path / "state")
