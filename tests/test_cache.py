from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

import deadlock_build_sync.cache_discovery as cache_discovery_module
import deadlock_build_sync.cache_install as cache_install_module
import deadlock_build_sync.cache_storage as cache_storage_module
from deadlock_build_sync.cache import (
    CacheError,
    CacheLocation,
    discover_cache,
    install_guides,
    read_cache,
    restore_latest,
    steam_roots,
    update_managed_builds,
)
from deadlock_build_sync.kv3_binary import encode_binary_v4
from deadlock_build_sync.protobuf import (
    hero_build_metadata,
)
from deadlock_build_sync.snapshot import sha256_json
from tests.cache_fixtures import (
    SNAPSHOT_ID,
    complete_guide,
    create_discoverable_cache,
    guide,
    set_deadlock_check,
    snapshot_manifest,
    unpublished,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_discover_cache_handles_missing_steam_installation(tmp_path: Path) -> None:
    with pytest.raises(CacheError, match="no Deadlock Steam Cloud cache found"):
        discover_cache(root=tmp_path / "missing")


def test_discover_cache_supports_flatpak_steam(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flatpak_root = tmp_path / ".var/app/com.valvesoftware.Steam/.local/share/Steam"
    expected = create_discoverable_cache(flatpak_root, 146293212)
    monkeypatch.setattr(cache_discovery_module.Path, "home", lambda: tmp_path)

    location = discover_cache()

    assert location.account_id == 146293212
    assert location.cache_path == expected.resolve()


def test_discover_cache_deduplicates_legacy_steam_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    native_root = tmp_path / ".local/share/Steam"
    expected = create_discoverable_cache(native_root, 146293212)
    legacy_root = tmp_path / ".steam/steam"
    legacy_root.parent.mkdir(parents=True)
    legacy_root.symlink_to(native_root, target_is_directory=True)
    monkeypatch.setattr(cache_discovery_module.Path, "home", lambda: tmp_path)

    roots = steam_roots(home=tmp_path)
    location = discover_cache()

    assert location.cache_path == expected.resolve()
    assert len(roots) == 4


def test_discover_cache_requires_path_for_duplicate_account_installations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    native_root = tmp_path / ".local/share/Steam"
    flatpak_root = tmp_path / ".var/app/com.valvesoftware.Steam/.local/share/Steam"
    create_discoverable_cache(native_root, 146293212)
    create_discoverable_cache(flatpak_root, 146293212)
    monkeypatch.setattr(cache_discovery_module.Path, "home", lambda: tmp_path)

    with pytest.raises(CacheError, match="pass --cache-path"):
        discover_cache(account_id=146293212)


def test_managed_update_is_idempotent_and_preserves_other_sections() -> None:
    root: dict[str, object] = {
        "LastUsedBuilds": {"hero_kelvin": 777},
        "Favorites": [b"favorite"],
        "Unpublished": [],
        "SavedLastUsed": [b"saved"],
    }
    first, ids, created, updated, removed = update_managed_builds(
        root,
        [guide()],
        account_id=146293212,
        persona="Player One",
        timestamp=100,
        patch_title="Patch",
        patch_published_at="2026-01-01T00:00:00Z",
    )
    assert created == 1
    assert updated == 0
    assert removed == 0
    assert ids == {(12, "default"): 2}
    assert first["Favorites"] == root["Favorites"]
    assert first["SavedLastUsed"] == root["SavedLastUsed"]
    assert first["LastUsedBuilds"] == root["LastUsedBuilds"]

    first_build = unpublished(first)[0]
    assert isinstance(first_build, bytes)
    first_metadata = hero_build_metadata(first_build)
    assert first_metadata.name is not None
    assert first_metadata.name.startswith("Player One | ")

    second, ids2, created2, updated2, removed2 = update_managed_builds(
        first,
        [guide()],
        account_id=146293212,
        persona="Player One",
        timestamp=200,
        patch_title="Patch 2",
        patch_published_at="2026-02-01T00:00:00Z",
    )
    assert ids2 == ids
    assert created2 == 0
    assert updated2 == 1
    assert removed2 == 0
    second_builds = unpublished(second)
    assert len(second_builds) == 1
    second_build = second_builds[0]
    assert isinstance(second_build, bytes)
    assert hero_build_metadata(second_build).build_id == 2


def test_multiple_paths_get_separate_builds_and_stale_path_is_removed() -> None:
    root: dict[str, object] = {
        "LastUsedBuilds": {"hero_kelvin": 77},
        "Favorites": [b"favorite"],
        "Unpublished": [],
        "SavedLastUsed": [b"saved"],
    }
    control = replace(
        guide(),
        path_id="control",
        path_label="Control Core",
        policy_id="policy/control",
    )
    damage = replace(
        guide(),
        path_id="damage",
        path_label="Damage Core",
        policy_id="policy/damage",
    )

    first, ids, created, updated, removed = update_managed_builds(
        root,
        [control, damage],
        account_id=146293212,
        persona="XMLJDX",
        timestamp=100,
        patch_title="Patch",
        patch_published_at="2026-01-01T00:00:00Z",
    )

    assert set(ids) == {(12, "control"), (12, "damage")}
    assert (created, updated, removed) == (2, 0, 0)
    assert len(unpublished(first)) == 2

    second, second_ids, created, updated, removed = update_managed_builds(
        first,
        [control],
        account_id=146293212,
        persona="XMLJDX",
        timestamp=200,
        patch_title="Patch",
        patch_published_at="2026-01-01T00:00:00Z",
    )

    assert second_ids == {(12, "control"): ids[12, "control"]}
    assert (created, updated, removed) == (0, 1, 1)
    assert len(unpublished(second)) == 1
    assert second["LastUsedBuilds"] == root["LastUsedBuilds"]
    assert second["Favorites"] == root["Favorites"]
    assert second["SavedLastUsed"] == root["SavedLastUsed"]


def test_v4_cache_decodes_after_managed_update(tmp_path: Path) -> None:
    root: dict[str, object] = {
        "LastUsedBuilds": {},
        "Favorites": [],
        "Unpublished": [],
        "SavedLastUsed": [],
    }
    updated, _, _, _, _ = update_managed_builds(
        root,
        [guide()],
        account_id=146293212,
        persona="XMLJDX",
        timestamp=100,
        patch_title="Patch",
        patch_published_at="2026-01-01T00:00:00Z",
    )
    path = tmp_path / "cached_hero_builds.kv3"
    path.write_bytes(encode_binary_v4(updated))
    decoded = read_cache(path)
    assert len(unpublished(decoded)) == 1


def test_install_creates_backup_and_restore_recovers_original(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_at = datetime(2026, 1, 2, tzinfo=UTC)

    class FixedDatetime:
        @staticmethod
        def now(_timezone: object) -> datetime:
            return created_at

    monkeypatch.setattr(cache_install_module, "datetime", FixedDatetime)
    monkeypatch.setattr(cache_storage_module, "datetime", FixedDatetime)
    app_directory = tmp_path / "userdata/146293212/1422450"
    cache_path = app_directory / "remote/cfg/cached_hero_builds.kv3"
    cache_path.parent.mkdir(parents=True)
    original: dict[str, object] = {
        "LastUsedBuilds": {"hero_kelvin": 777},
        "Favorites": [],
        "Unpublished": [],
        "SavedLastUsed": [],
    }
    cache_path.write_bytes(encode_binary_v4(original))
    (app_directory / "remotecache.vdf").write_text(
        '"remote cache"',
        encoding="utf-8",
    )
    location = CacheLocation(146293212, cache_path, app_directory)
    state_root = tmp_path / "state"
    set_deadlock_check(monkeypatch, lambda: False)

    result = install_guides(
        location,
        [complete_guide()],
        persona="XMLJDX",
        timestamp=100,
        patch_title="Patch",
        patch_published_at="2026-01-01T00:00:00Z",
        backup_root=state_root,
        snapshot_manifest=snapshot_manifest(),
        expected_hero_ids={12},
    )
    assert hashlib.sha256(cache_path.read_bytes()).hexdigest() == (
        "693a43b4e26dfff60d0e9620e7ec3e185c33844bed0396386efab9e87328f4f2"
    )
    manifest = json.loads(
        (result.backup_directory / "manifest.json").read_text(encoding="utf-8")
    )
    manifest["cache_path"] = "<cache>"
    assert sha256_json(manifest) == (
        "68e8d42bb3d815c66ebdbbcff2fdbe5a77de3282c1af7a124b934e50e1c57f31"
    )
    assert result.created == 1
    assert (result.backup_directory / "cached_hero_builds.kv3").is_file()
    assert (result.backup_directory / "remotecache.vdf").is_file()
    assert result.snapshot_id == SNAPSHOT_ID
    assert result.policy_ids == {(12, "default"): "policy/kelvin"}
    installed = read_cache(cache_path)
    assert installed["LastUsedBuilds"] == original["LastUsedBuilds"]
    assert len(unpublished(installed)) == 1

    restored_from = restore_latest(location, backup_root=state_root)
    assert restored_from == result.backup_directory
    assert read_cache(cache_path) == original
    assert (app_directory / "remotecache.vdf").read_text(
        encoding="utf-8"
    ) == '"remote cache"'


def test_install_rejects_incomplete_item_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_directory = tmp_path / "userdata/146293212/1422450"
    cache_path = app_directory / "remote/cfg/cached_hero_builds.kv3"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_bytes(
        encode_binary_v4({
            "LastUsedBuilds": {},
            "Favorites": [],
            "Unpublished": [],
            "SavedLastUsed": [],
        })
    )
    location = CacheLocation(146293212, cache_path, app_directory)
    set_deadlock_check(monkeypatch, lambda: False)
    guides = [guide()]
    manifest = snapshot_manifest()

    with pytest.raises(CacheError, match="incomplete policy identity/projection"):
        install_guides(
            location,
            guides,
            persona="XMLJDX",
            timestamp=100,
            patch_title="Patch",
            patch_published_at="2026-01-01T00:00:00Z",
            backup_root=tmp_path / "state",
            snapshot_manifest=manifest,
        )
