from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .protobuf import (
    HeroBuildMetadata,
    is_managed_build,
    managed_build_path,
    try_hero_build_metadata,
)
from .value_validation import object_list

if TYPE_CHECKING:
    from .purchase_guide import PurchaseGuide


from .cache_discovery import deadlock_is_running
from .cache_projection import read_cache
from .cache_types import (
    _CACHE_FILENAME,
    BuildKey,
    CacheError,
    CacheLocation,
    _GuideInstallationIdentity,
    _ReplacementValidation,
)

_CACHE_JSON_ENCODER = json.JSONEncoder(
    ensure_ascii=False,
    separators=(",", ":"),
)
_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)


def _state_root() -> Path:
    configured = os.environ.get("XDG_STATE_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".local/state"


def _create_backup(location: CacheLocation, *, root: Path | None = None) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    parent = (
        (root or _state_root())
        / "deadlock-build-sync/backups"
        / str(location.account_id)
    )
    backup = parent / timestamp
    suffix = 1
    while backup.exists():
        backup = parent / f"{timestamp}-{suffix}"
        suffix += 1
    backup.mkdir(parents=True)
    shutil.copy2(location.cache_path, backup / _CACHE_FILENAME)
    if location.remote_cache_path.is_file():
        shutil.copy2(location.remote_cache_path, backup / "remotecache.vdf")
    for path in backup.iterdir():
        if path.is_file():
            with path.open("rb") as copied:
                os.fsync(copied.fileno())
    _fsync_directory(backup)
    _fsync_directory(parent)
    return backup


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | _O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _stable_cache_value(value: object) -> object:
    if isinstance(value, dict):
        return {
            str(key): _stable_cache_value(nested)
            for key, nested in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, list):
        return [_stable_cache_value(nested) for nested in value]
    if isinstance(value, (bytes, bytearray)):
        return {"bytes_sha256": hashlib.sha256(bytes(value)).hexdigest()}
    return value


def _is_target_managed_blob(
    value: object,
    *,
    account_id: int,
    target_hero_ids: set[int],
) -> bool:
    metadata = try_hero_build_metadata(value)
    if metadata is None:
        return False
    hero_id = metadata.hero_id
    return (
        hero_id is not None
        and hero_id in target_hero_ids
        and is_managed_build(
            metadata,
            hero_id=hero_id,
            account_id=account_id,
        )
    )


def _out_of_scope_fingerprint(
    root: dict[str, object],
    *,
    account_id: int,
    target_hero_ids: set[int],
) -> str:
    projection = {
        key: (
            [
                value
                for value in nested
                if not _is_target_managed_blob(
                    value,
                    account_id=account_id,
                    target_hero_ids=target_hero_ids,
                )
            ]
            if key == "Unpublished" and isinstance(nested, list)
            else nested
        )
        for key, nested in root.items()
    }
    normalized = _stable_cache_value(projection)
    encoded = _CACHE_JSON_ENCODER.encode(normalized).encode()
    return hashlib.sha256(encoded).hexdigest()


def _target_managed_metadata(
    blob: object,
    expected: dict[BuildKey, int],
    account_id: int,
) -> tuple[BuildKey, HeroBuildMetadata] | None:
    metadata = try_hero_build_metadata(blob)
    if metadata is None:
        return None
    if metadata.author_account_id != account_id:
        return None
    candidate = metadata.hero_id, managed_build_path(metadata)
    return next(
        ((key, metadata) for key in expected if key == candidate),
        None,
    )


def _validate_managed_identity(
    key: BuildKey,
    metadata: HeroBuildMetadata,
    identities: dict[BuildKey, tuple[str, str]],
) -> int:
    hero_id, path_id = key
    if metadata.build_id is None:
        raise CacheError(
            f"replacement cache managed build {hero_id}/{path_id} has no build ID"
        )
    expected_identity = identities.get(key)
    if expected_identity is None:
        return metadata.build_id
    snapshot_id, policy_id = expected_identity
    description = metadata.description
    if description is None:
        raise CacheError(
            f"replacement cache managed build {hero_id}/{path_id} has stale identity"
        )
    if (
        f"Snapshot: {snapshot_id}." not in description
        or f"Policy: {policy_id}." not in description
    ):
        raise CacheError(
            f"replacement cache managed build {hero_id}/{path_id} has stale identity"
        )
    return metadata.build_id


def _validate_managed_entries(
    root: dict[str, object],
    expected: dict[BuildKey, int],
    *,
    account_id: int,
    identities: dict[BuildKey, tuple[str, str]] | None = None,
) -> None:
    found: dict[BuildKey, int] = {}
    unpublished = object_list(root.get("Unpublished"))
    if unpublished is None:
        raise CacheError("replacement cache Unpublished section is not an array")
    for blob in unpublished:
        target = _target_managed_metadata(blob, expected, account_id)
        if target is None:
            continue
        key, metadata = target
        if key in found:
            raise CacheError(
                f"replacement cache contains duplicate managed build {key[0]}/{key[1]}"
            )
        found[key] = _validate_managed_identity(key, metadata, identities or {})
    if found != expected:
        raise CacheError(
            f"replacement cache validation failed: expected {expected}, found {found}"
        )


def _restore_cache_file(source: Path, destination: Path) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".cached_hero_builds.restore.",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as output:
            temporary = Path(output.name)
            with source.open("rb") as backup:
                shutil.copyfileobj(backup, output)
            output.flush()
            os.fsync(output.fileno())
        read_cache(temporary)
        temporary.replace(destination)
        temporary = None
        _fsync_directory(destination.parent)
        read_cache(destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _validate_install_coverage(
    hero_ids: set[int],
    expected_hero_ids: set[int] | None,
    *,
    allow_subset: bool,
) -> None:
    if expected_hero_ids is None or allow_subset:
        return
    missing = expected_hero_ids - hero_ids
    extra = hero_ids - expected_hero_ids
    if missing or extra:
        raise CacheError(
            "all-hero installation coverage mismatch; missing "
            f"{sorted(missing)}, extra {sorted(extra)}"
        )


def _validate_install_request(
    guides: list[PurchaseGuide],
    snapshot_manifest: dict[str, object] | None,
    expected_hero_ids: set[int] | None,
    *,
    allow_subset: bool,
) -> _GuideInstallationIdentity:
    if not guides:
        raise CacheError("no guides were generated")
    incomplete = [
        guide.hero_name
        for guide in guides
        if not guide.rendered_categories
        or not any(not category.optional for category in guide.rendered_categories)
        or not guide.snapshot_id
        or not guide.policy_id
        or guide.client_version is None
        or not guide.match_mode
        or not guide.rank_identity
    ]
    if incomplete:
        raise CacheError(
            "refusing to install guides with incomplete policy identity/projection: "
            + ", ".join(incomplete)
        )
    hero_ids = {guide.hero_id for guide in guides}
    build_keys = {(guide.hero_id, guide.path_id) for guide in guides}
    if len(build_keys) != len(guides):
        raise CacheError("refusing to install duplicate hero/build-path guides")
    _validate_install_coverage(
        hero_ids,
        expected_hero_ids,
        allow_subset=allow_subset,
    )
    snapshot_ids = {guide.snapshot_id for guide in guides}
    if len(snapshot_ids) != 1:
        raise CacheError("all installed guides must use one snapshot")
    snapshot_id = next(iter(snapshot_ids))
    if snapshot_manifest is None or snapshot_manifest.get("snapshot_id") != snapshot_id:
        raise CacheError("install snapshot manifest is missing or incompatible")
    policy_ids = {(guide.hero_id, guide.path_id): guide.policy_id for guide in guides}
    identities = {
        (guide.hero_id, guide.path_id): (guide.snapshot_id, guide.policy_id)
        for guide in guides
    }
    return _GuideInstallationIdentity(
        hero_ids,
        build_keys,
        snapshot_id,
        policy_ids,
        identities,
    )


def _validate_replacement_cache(
    root: dict[str, object],
    validation: _ReplacementValidation,
    scope_error: str,
) -> None:
    _validate_managed_entries(
        root,
        validation.build_ids,
        account_id=validation.account_id,
        identities=validation.identities,
    )
    fingerprint = _out_of_scope_fingerprint(
        root,
        account_id=validation.account_id,
        target_hero_ids=validation.hero_ids,
    )
    if fingerprint != validation.out_of_scope_sha256:
        raise CacheError(scope_error)


def _install_replacement(
    location: CacheLocation,
    encoded: bytes,
    validation: _ReplacementValidation,
) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".cached_hero_builds.",
            suffix=".tmp",
            dir=location.cache_path.parent,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(encoded)
            temporary.flush()
            os.fsync(temporary.fileno())
        candidate = read_cache(temporary_path)
        _validate_replacement_cache(
            candidate,
            validation,
            "replacement cache changed out-of-scope Steam data",
        )
        if deadlock_is_running():
            raise CacheError(
                "Deadlock started before replacement; refusing to change the cache"
            )
        temporary_path.replace(location.cache_path)
        temporary_path = None
        _fsync_directory(location.cache_path.parent)
        installed = read_cache(location.cache_path)
        _validate_replacement_cache(
            installed,
            validation,
            "installed cache changed out-of-scope Steam data",
        )
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
