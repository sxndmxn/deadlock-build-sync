from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from .artifacts import atomic_write_json
from .kv3_binary import encode_binary_v4
from .ranks import DEFAULT_RANK_RANGE
from .renderer import projection_fingerprint

if TYPE_CHECKING:
    from pathlib import Path

    from .purchase_guide import PurchaseGuide
    from .ranks import RankRange


from .cache_discovery import deadlock_is_running
from .cache_projection import read_cache, update_managed_builds
from .cache_storage import (
    _calculate_unmanaged_cache_fingerprint,
    _create_backup,
    _install_replacement,
    _resolve_state_root,
    _restore_cache_file,
    _validate_install_request,
)
from .cache_types import (
    _CACHE_FILENAME,
    CacheError,
    CacheLocation,
    InstallResult,
    _CacheReplacementError,
    _ReplacementValidation,
)


def install_guides(
    location: CacheLocation,
    guides: list[PurchaseGuide],
    *,
    persona: str,
    timestamp: int,
    patch_title: str,
    patch_published_at: str,
    rank_range: RankRange = DEFAULT_RANK_RANGE,
    backup_root: Path | None = None,
    snapshot_manifest: dict[str, object] | None = None,
    expected_hero_ids: set[int] | None = None,
    allow_subset: bool = False,
) -> InstallResult:
    if deadlock_is_running():
        raise CacheError(
            "Deadlock is running; close it before installing private builds"
        )
    identity = _validate_install_request(
        guides,
        snapshot_manifest,
        expected_hero_ids,
        allow_subset=allow_subset,
    )

    original = read_cache(location.cache_path)
    original_out_of_scope = _calculate_unmanaged_cache_fingerprint(
        original,
        account_id=location.account_id,
        target_hero_ids=identity.hero_ids,
    )
    replacement, build_ids, created, updated, removed = update_managed_builds(
        original,
        guides,
        account_id=location.account_id,
        persona=persona,
        timestamp=timestamp,
        patch_title=patch_title,
        patch_published_at=patch_published_at,
        rank_range=rank_range,
    )
    encoded = encode_binary_v4(replacement)

    backup = _create_backup(location, root=backup_root)
    installed_builds = [
        {
            "hero_id": guide.hero_id,
            "path_id": guide.path_id,
            "build_id": build_ids[guide.hero_id, guide.path_id],
            "policy_id": guide.policy_id,
            "projection_fingerprint": projection_fingerprint(guide),
        }
        for guide in guides
    ]
    manifest: dict[str, object] = {
        "account_id": location.account_id,
        "cache_path": str(location.cache_path),
        "created_at": datetime.now(UTC).isoformat(),
        "builds": installed_builds,
        "rank_range": rank_range.as_dict(),
        "snapshot": snapshot_manifest,
        "snapshot_id": identity.snapshot_id,
        "out_of_scope_sha256": original_out_of_scope,
    }
    atomic_write_json(backup / "manifest.json", manifest)

    validation = _ReplacementValidation(
        location.account_id,
        build_ids,
        identity.identities,
        identity.hero_ids,
        original_out_of_scope,
    )
    try:
        _install_replacement(location, encoded, validation)
    except _CacheReplacementError as error:
        try:
            _restore_cache_file(
                backup / _CACHE_FILENAME,
                location.cache_path,
            )
        except Exception as restore_error:
            raise CacheError(
                f"installation failed ({error}) and automatic restore failed ({restore_error}); "
                f"backup is at {backup}"
            ) from restore_error
        raise CacheError(
            f"installation failed and the original cache was restored: {error}"
        ) from error
    except CacheError:
        raise
    except Exception as error:
        raise CacheError(
            f"Installation failed before cache replacement: {error}"
        ) from error

    return InstallResult(
        location.cache_path,
        backup,
        build_ids,
        created,
        updated,
        removed,
        identity.snapshot_id,
        identity.policy_ids,
    )


def restore_latest(
    location: CacheLocation,
    *,
    backup_root: Path | None = None,
) -> Path:
    if deadlock_is_running():
        raise CacheError(
            "Deadlock is running; close it before restoring a cache backup"
        )
    parent = (
        (backup_root or _resolve_state_root())
        / "deadlock-build-sync/backups"
        / str(location.account_id)
    )
    backups = (
        sorted(
            (path for path in parent.iterdir() if (path / _CACHE_FILENAME).is_file()),
            reverse=True,
        )
        if parent.is_dir()
        else []
    )
    if not backups:
        raise CacheError(f"no cache backups found for account {location.account_id}")
    source = backups[0] / _CACHE_FILENAME
    read_cache(source)
    _restore_cache_file(source, location.cache_path)
    return backups[0]
