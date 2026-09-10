from __future__ import annotations

from typing import TYPE_CHECKING

import deadlock_build_sync.cache_install as cache_install_module
import deadlock_build_sync.cache_storage as cache_storage_module
from deadlock_build_sync.cache import (
    CacheLocation,
    install_guides,
)
from deadlock_build_sync.kv3_binary import encode_binary_v4
from deadlock_build_sync.purchase_guide import GuideItem, PurchaseGuide, PurchaseWindow
from deadlock_build_sync.value_validation import require_object_list

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import pytest

SNAPSHOT_ID = "c" * 64


def set_deadlock_check(
    monkeypatch: pytest.MonkeyPatch,
    check: Callable[[], bool],
) -> None:
    monkeypatch.setattr(cache_install_module, "deadlock_is_running", check)
    monkeypatch.setattr(cache_storage_module, "deadlock_is_running", check)


def make_snapshot_manifest() -> dict[str, object]:
    return {"snapshot_id": SNAPSHOT_ID}


def make_unpublished_build(root: dict[str, object]) -> list[object]:
    return require_object_list(root["Unpublished"])


def make_purchase_guide() -> PurchaseGuide:
    window = PurchaseWindow(5000, 10000, 100, 60, 0.6, 0.5)
    item = GuideItem(123, "Test Item", 1, 200, 0.55, 0.48, 1.0, (window,))
    return PurchaseGuide(
        12,
        "Kelvin",
        "hero_kelvin",
        {1: (item,), 2: (), 3: (), 4: ()},
        build_tag_ids=(1, 2, 3),
        analysis_start_timestamp=1_767_225_600,
        as_of_timestamp=1_767_225_600,
    )


def make_complete_guide() -> PurchaseGuide:
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
    return PurchaseGuide(
        12,
        "Kelvin",
        "hero_kelvin",
        tiers,
        snapshot_id=SNAPSHOT_ID,
        policy_id="policy/kelvin",
        client_version=123,
        match_mode="ranked",
        rank_identity="Phantom I [91]–Eternus VI [116]",
        build_tag_ids=(1, 2, 3),
        build_archetype="Spirit Damage",
        analysis_start_timestamp=1_767_225_600,
        as_of_timestamp=1_767_225_600,
    )


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


def make_isolated_cache_location(
    tmp_path: Path,
) -> tuple[CacheLocation, dict[str, object]]:
    app_directory = tmp_path / "userdata/146293212/1422450"
    cache_path = app_directory / "remote/cfg/cached_hero_builds.kv3"
    cache_path.parent.mkdir(parents=True)
    original: dict[str, object] = {
        "LastUsedBuilds": {"hero_kelvin": 777},
        "Favorites": [b"favorite"],
        "Unpublished": [b"unrelated-private-build"],
        "SavedLastUsed": [b"saved"],
        "UnknownFutureField": {"nested": [1, b"opaque"]},
    }
    cache_path.write_bytes(encode_binary_v4(original))
    return CacheLocation(146293212, cache_path, app_directory), original


def install_complete_guide(
    location: CacheLocation,
    backup_root: Path,
) -> None:
    install_guides(
        location,
        [make_complete_guide()],
        persona="XMLJDX",
        timestamp=100,
        patch_title="Patch",
        patch_published_at="2026-01-01T00:00:00Z",
        backup_root=backup_root,
        snapshot_manifest=make_snapshot_manifest(),
        expected_hero_ids={12},
    )
