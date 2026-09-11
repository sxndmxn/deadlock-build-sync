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
from deadlock_build_sync.kv3_binary import encode_binary_v4
from tests.cache_fixtures import (
    install_complete_guide,
    make_complete_guide,
    make_isolated_cache_location,
    make_snapshot_manifest,
    set_deadlock_check,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_install_refuses_if_deadlock_starts_at_mutation_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    location, original = make_isolated_cache_location(tmp_path)
    states = iter((False, True))
    set_deadlock_check(monkeypatch, lambda: next(states))

    with pytest.raises(CacheError, match="started before replacement"):
        install_complete_guide(location, tmp_path / "state")

    assert read_cache(location.cache_path) == original


def test_install_refusal_preserves_cache_changes_after_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    location, original = make_isolated_cache_location(tmp_path)
    updated = {**original, "Favorites": [b"new-favorite"]}
    checks = 0
    replacements: list[Path] = []
    real_replace = type(location.cache_path).replace

    def check_running() -> bool:
        nonlocal checks
        checks += 1
        if checks == 1:
            return False
        location.cache_path.write_bytes(encode_binary_v4(updated))
        return True

    def record_replace(source: Path, destination: Path) -> Path:
        if destination == location.cache_path:
            replacements.append(source)
        return real_replace(source, destination)

    set_deadlock_check(monkeypatch, check_running)
    monkeypatch.setattr(type(location.cache_path), "replace", record_replace)
    with pytest.raises(CacheError, match="started before replacement"):
        install_complete_guide(location, tmp_path / "state")

    assert replacements == []
    assert read_cache(location.cache_path) == updated
    backups = list((tmp_path / "state").rglob("cached_hero_builds.kv3"))
    assert len(backups) == 1
    assert read_cache(backups[0]) == original


def test_install_restores_after_directory_fsync_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    location, original = make_isolated_cache_location(tmp_path)
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
        install_complete_guide(location, tmp_path / "state")

    assert read_cache(location.cache_path) == original


def test_out_of_scope_corruption_is_detected_and_restored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    location, original = make_isolated_cache_location(tmp_path)
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
        install_complete_guide(location, tmp_path / "state")

    assert real_read_cache(location.cache_path) == original


def test_all_hero_installation_refuses_missing_roster_member(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    location, original = make_isolated_cache_location(tmp_path)
    set_deadlock_check(monkeypatch, lambda: False)
    guides = [make_complete_guide()]
    manifest = make_snapshot_manifest()

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
    location, _ = make_isolated_cache_location(tmp_path)
    set_deadlock_check(monkeypatch, lambda: False)
    real_fsync = cache_storage_module._fsync_directory

    def fail_after_replacement(path: Path) -> None:
        if path == location.cache_path.parent:
            raise OSError("Directory synchronization failed")
        real_fsync(path)

    monkeypatch.setattr(
        cache_storage_module, "_fsync_directory", fail_after_replacement
    )
    monkeypatch.setattr(
        cache_install_module,
        "_restore_cache_file",
        lambda _source, _destination: (_ for _ in ()).throw(OSError("restore failed")),
    )

    with pytest.raises(CacheError, match=r"automatic restore failed.*backup is at"):
        install_complete_guide(location, tmp_path / "state")


@pytest.mark.parametrize("failure", [OSError, CacheError])
def test_validation_failure_before_replacement_preserves_the_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: type[Exception]
) -> None:
    location, original = make_isolated_cache_location(tmp_path)
    updated = {**original, "Favorites": [b"concurrent-favorite"]}
    set_deadlock_check(monkeypatch, lambda: False)

    def reject_candidate(*_args: object) -> None:
        location.cache_path.write_bytes(encode_binary_v4(updated))
        raise failure("Candidate validation failed")

    monkeypatch.setattr(
        cache_storage_module, "_validate_replacement_cache", reject_candidate
    )
    with pytest.raises(CacheError, match="Candidate validation failed"):
        install_complete_guide(location, tmp_path / "state")
    assert read_cache(location.cache_path) == updated


def test_recovery_refuses_if_deadlock_starts_after_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    location, original = make_isolated_cache_location(tmp_path)
    updated = {**original, "Favorites": [b"concurrent-favorite"]}
    checks = iter((False, False, True))
    set_deadlock_check(monkeypatch, lambda: next(checks))
    real_fsync = cache_storage_module._fsync_directory

    def fail_after_replacement(path: Path) -> None:
        if path == location.cache_path.parent:
            location.cache_path.write_bytes(encode_binary_v4(updated))
            raise OSError("Directory synchronization failed")
        real_fsync(path)

    monkeypatch.setattr(
        cache_storage_module, "_fsync_directory", fail_after_replacement
    )
    with pytest.raises(
        CacheError, match=r"started before restore.*backup is at"
    ) as error:
        install_complete_guide(location, tmp_path / "state")
    assert read_cache(location.cache_path) == updated
    assert isinstance(error.value.__cause__, CacheError)
    assert str(error.value.__cause__) == (
        "Deadlock started before restore; refusing to change the cache"
    )
