from pathlib import Path

import pytest

import deadlock_build_sync.cache as cache_module
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
    encode_hero_build,
    hero_build_metadata,
    wrap_hero_build,
)
from deadlock_build_sync.purchase_guide import GuideItem, PurchaseGuide, PurchaseWindow


def guide() -> PurchaseGuide:
    window = PurchaseWindow(5000, 10000, 100, 60, 0.6, 0.5)
    item = GuideItem(123, "Test Item", 1, 200, 0.55, 0.48, 1.0, (window,))
    return PurchaseGuide(12, "Kelvin", "hero_kelvin", {1: (item,), 2: (), 3: (), 4: ()})


def complete_guide() -> PurchaseGuide:
    window = PurchaseWindow(5000, 10000, 100, 60, 0.6, 0.5)
    tiers = {
        tier: tuple(
            GuideItem(
                tier * 100 + index,
                f"Tier {tier} Item {index}",
                tier,
                200,
                0.55,
                0.48,
                1.0,
                (window,),
            )
            for index in range(8)
        )
        for tier in range(1, 5)
    }
    return PurchaseGuide(12, "Kelvin", "hero_kelvin", tiers)


def existing_blob(
    build_id: int, hero_id: int, description_patch: str = "Existing"
) -> bytes:
    build = encode_hero_build(
        PurchaseGuide(
            hero_id, "Existing", "hero_existing", {1: (), 2: (), 3: (), 4: ()}
        ),
        build_id=build_id,
        account_id=146293212,
        persona="XMLJDX",
        timestamp=1,
        patch_title=description_patch,
        patch_published_at="2026-01-01T00:00:00Z",
    )
    return wrap_hero_build(build)


def create_discoverable_cache(root: Path, account_id: int) -> Path:
    path = (
        root
        / "userdata"
        / str(account_id)
        / "1422450/remote/cfg/cached_hero_builds.kv3"
    )
    path.parent.mkdir(parents=True)
    path.touch()
    return path


def test_discover_cache_handles_missing_steam_installation(tmp_path: Path) -> None:
    with pytest.raises(CacheError, match="no Deadlock Steam Cloud cache found"):
        discover_cache(root=tmp_path / "missing")


def test_discover_cache_supports_flatpak_steam(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flatpak_root = tmp_path / ".var/app/com.valvesoftware.Steam/.local/share/Steam"
    expected = create_discoverable_cache(flatpak_root, 146293212)
    monkeypatch.setattr(cache_module.Path, "home", lambda: tmp_path)

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
    monkeypatch.setattr(cache_module.Path, "home", lambda: tmp_path)

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
    monkeypatch.setattr(cache_module.Path, "home", lambda: tmp_path)

    with pytest.raises(CacheError, match="pass --cache-path"):
        discover_cache(account_id=146293212)


def test_managed_update_is_idempotent_and_preserves_other_sections() -> None:
    root = {
        "LastUsedBuilds": {"hero_kelvin": 777},
        "Favorites": [b"favorite"],
        "Unpublished": [],
        "SavedLastUsed": [b"saved"],
    }
    first, ids, created, updated = update_managed_builds(
        root,
        [guide()],
        account_id=146293212,
        persona="XMLJDX",
        timestamp=100,
        patch_title="Patch",
        patch_published_at="2026-01-01T00:00:00Z",
    )
    assert created == 1 and updated == 0
    assert ids == {12: 2}
    assert first["Favorites"] == root["Favorites"]
    assert first["SavedLastUsed"] == root["SavedLastUsed"]
    assert first["LastUsedBuilds"] == root["LastUsedBuilds"]

    second, ids2, created2, updated2 = update_managed_builds(
        first,
        [guide()],
        account_id=146293212,
        persona="XMLJDX",
        timestamp=200,
        patch_title="Patch 2",
        patch_published_at="2026-02-01T00:00:00Z",
    )
    assert ids2 == ids
    assert created2 == 0 and updated2 == 1
    assert len(second["Unpublished"]) == 1
    assert hero_build_metadata(second["Unpublished"][0]).build_id == 2


def test_v4_cache_decodes_after_managed_update(tmp_path: Path) -> None:
    root = {
        "LastUsedBuilds": {},
        "Favorites": [],
        "Unpublished": [],
        "SavedLastUsed": [],
    }
    updated, _, _, _ = update_managed_builds(
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
    assert len(decoded["Unpublished"]) == 1


def test_install_creates_backup_and_restore_recovers_original(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_directory = tmp_path / "userdata/146293212/1422450"
    cache_path = app_directory / "remote/cfg/cached_hero_builds.kv3"
    cache_path.parent.mkdir(parents=True)
    original = {
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
    monkeypatch.setattr(cache_module, "deadlock_is_running", lambda: False)

    result = install_guides(
        location,
        [complete_guide()],
        persona="XMLJDX",
        timestamp=100,
        patch_title="Patch",
        patch_published_at="2026-01-01T00:00:00Z",
        backup_root=state_root,
    )
    assert result.created == 1
    assert (result.backup_directory / "cached_hero_builds.kv3").is_file()
    assert (result.backup_directory / "remotecache.vdf").is_file()
    installed = read_cache(cache_path)
    assert installed["LastUsedBuilds"] == original["LastUsedBuilds"]
    assert len(installed["Unpublished"]) == 1

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
    monkeypatch.setattr(cache_module, "deadlock_is_running", lambda: False)

    with pytest.raises(CacheError, match="incomplete item coverage"):
        install_guides(
            location,
            [guide()],
            persona="XMLJDX",
            timestamp=100,
            patch_title="Patch",
            patch_published_at="2026-01-01T00:00:00Z",
            backup_root=tmp_path / "state",
        )
