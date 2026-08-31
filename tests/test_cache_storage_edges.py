from dataclasses import replace
from pathlib import Path

import pytest

from deadlock_build_sync import cache_storage
from deadlock_build_sync.cache import CacheError, update_managed_builds
from deadlock_build_sync.protobuf import hero_build_metadata
from tests.cache_fixtures import (
    complete_guide,
    isolated_location,
    snapshot_manifest,
    unpublished,
)


def _managed_root() -> tuple[dict[str, object], dict[tuple[int, str], int], bytes]:
    root: dict[str, object] = {"Unpublished": []}
    updated, build_ids, _, _, _ = update_managed_builds(
        root,
        [complete_guide()],
        account_id=146293212,
        persona="Player",
        timestamp=100,
        patch_title="Patch",
        patch_published_at="2026-01-01T00:00:00Z",
    )
    blob = unpublished(updated)[0]
    assert isinstance(blob, bytes)
    return updated, build_ids, blob


def test_state_root_honors_xdg_and_uses_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    assert cache_storage._state_root() == tmp_path / "state"

    monkeypatch.delenv("XDG_STATE_HOME")
    monkeypatch.setattr(cache_storage.Path, "home", lambda: tmp_path)
    assert cache_storage._state_root() == tmp_path / ".local/state"


def test_backup_uses_suffix_and_copies_remote_metadata(tmp_path: Path) -> None:
    location, _ = isolated_location(tmp_path)
    location.remote_cache_path.write_text("remote", encoding="utf-8")
    root = tmp_path / "state"

    first = cache_storage._create_backup(location, root=root)
    second = cache_storage._create_backup(location, root=root)

    assert first != second
    assert (first / "remotecache.vdf").read_text(encoding="utf-8") == "remote"
    assert (second / "cached_hero_builds.kv3").is_file()


def test_stable_cache_value_normalizes_bytearray() -> None:
    normalized = cache_storage._stable_cache_value({"rows": [bytearray(b"value")]})

    assert normalized == {
        "rows": [
            {
                "bytes_sha256": (
                    "cd42404d52ad55ccfa9aca4adc828aa5800ad9d385a0671fbcbf724118320619"
                )
            }
        ]
    }


def test_managed_blob_helpers_ignore_bad_inputs() -> None:
    _, build_ids, blob = _managed_root()

    assert not cache_storage._is_target_managed_blob(
        "not-bytes", account_id=146293212, target_hero_ids={12}
    )
    assert not cache_storage._is_target_managed_blob(
        b"\xff", account_id=146293212, target_hero_ids={12}
    )
    assert (
        cache_storage._target_managed_metadata("not-bytes", build_ids, 146293212)
        is None
    )
    assert cache_storage._target_managed_metadata(b"\xff", build_ids, 146293212) is None
    assert cache_storage._target_managed_metadata(blob, build_ids, 99) is None


def test_managed_identity_requires_build_id_and_current_fingerprints() -> None:
    _, _, blob = _managed_root()
    metadata = hero_build_metadata(blob)
    key = (12, "default")

    with pytest.raises(CacheError, match="has no build ID"):
        cache_storage._validate_managed_identity(
            key,
            replace(metadata, build_id=None),
            {},
        )

    cache_storage._validate_managed_identity(key, metadata, {})
    with pytest.raises(CacheError, match="stale identity"):
        cache_storage._validate_managed_identity(
            key,
            metadata,
            {key: ("wrong-snapshot", "wrong-policy")},
        )


def test_managed_entry_validation_checks_section_duplicates_and_coverage() -> None:
    root, build_ids, blob = _managed_root()

    with pytest.raises(CacheError, match="not an array"):
        cache_storage._validate_managed_entries(
            {"Unpublished": {}}, build_ids, account_id=146293212
        )

    with pytest.raises(CacheError, match="duplicate managed build"):
        cache_storage._validate_managed_entries(
            {"Unpublished": [blob, blob]}, build_ids, account_id=146293212
        )

    with pytest.raises(CacheError, match="validation failed"):
        cache_storage._validate_managed_entries(
            root,
            {(13, "default"): 2},
            account_id=146293212,
        )


def test_restore_removes_temporary_file_after_copy_error(tmp_path: Path) -> None:
    location, _ = isolated_location(tmp_path)

    with pytest.raises(FileNotFoundError):
        cache_storage._restore_cache_file(
            tmp_path / "missing-backup",
            location.cache_path,
        )

    assert not list(location.cache_path.parent.glob("*.restore.*.tmp"))


def test_install_coverage_allows_unspecified_or_explicit_subsets() -> None:
    cache_storage._validate_install_coverage({12}, None, allow_subset=False)
    cache_storage._validate_install_coverage({12}, {12, 13}, allow_subset=True)


def test_install_request_rejects_empty_duplicate_and_mixed_guides() -> None:
    with pytest.raises(CacheError, match="no guides"):
        cache_storage._validate_install_request(
            [], snapshot_manifest(), {12}, allow_subset=False
        )

    guide = complete_guide()
    with pytest.raises(CacheError, match="duplicate hero/build-path"):
        cache_storage._validate_install_request(
            [guide, guide], snapshot_manifest(), {12}, allow_subset=False
        )

    other_snapshot = replace(guide, hero_id=13, snapshot_id="other")
    with pytest.raises(CacheError, match="use one snapshot"):
        cache_storage._validate_install_request(
            [guide, other_snapshot],
            snapshot_manifest(),
            None,
            allow_subset=True,
        )

    with pytest.raises(CacheError, match="manifest is missing or incompatible"):
        cache_storage._validate_install_request([guide], None, {12}, allow_subset=False)
