from __future__ import annotations

import io
import json
import os
import shutil
import struct
import tempfile
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import keyvalues3

from .kv3_binary import encode_binary_v4
from .protobuf import (
    MANAGED_MARKER,
    encode_hero_build,
    hero_build_metadata,
    is_managed_build,
    wrap_hero_build,
)
from .ranks import DEFAULT_RANK_RANGE

if TYPE_CHECKING:
    from .purchase_guide import PurchaseGuide
    from .ranks import RankRange

DEADLOCK_APP_ID = "1422450"
CACHE_RELATIVE_PATH = Path("remote/cfg/cached_hero_builds.kv3")
STEAM_ROOT_RELATIVE_PATHS = (
    Path(".local/share/Steam"),
    Path(".steam/steam"),
    Path(".steam/root"),
    Path(".var/app/com.valvesoftware.Steam/.local/share/Steam"),
    Path("snap/steam/common/.local/share/Steam"),
)


class CacheError(RuntimeError):
    """Raised when the Deadlock build cache cannot be safely changed."""


@dataclass(frozen=True)
class CacheLocation:
    account_id: int
    cache_path: Path
    app_directory: Path

    @property
    def remote_cache_path(self) -> Path:
        return self.app_directory / "remotecache.vdf"


@dataclass(frozen=True)
class InstallResult:
    cache_path: Path
    backup_directory: Path
    build_ids: dict[int, int]
    created: int
    updated: int


def steam_roots(*, home: Path | None = None) -> tuple[Path, ...]:
    base = home or Path.home()
    roots: list[Path] = []
    identities: set[Path] = set()
    for relative_path in STEAM_ROOT_RELATIVE_PATHS:
        candidate = base / relative_path
        identity = candidate.resolve(strict=False)
        if identity in identities:
            continue
        identities.add(identity)
        roots.append(candidate)
    return tuple(roots)


def steam_root() -> Path:
    roots = steam_roots()
    return next((root for root in roots if root.is_dir()), roots[0])


def _steam_accounts(userdata: Path, account_id: int | None) -> tuple[Path, ...]:
    if account_id is not None:
        return (userdata / str(account_id),)
    if not userdata.is_dir():
        return ()
    return tuple(
        path for path in userdata.iterdir() if path.is_dir() and path.name.isdigit()
    )


def discover_cache(
    *,
    account_id: int | None = None,
    cache_path: Path | None = None,
    root: Path | None = None,
) -> CacheLocation:
    if cache_path is not None:
        resolved = cache_path.expanduser().resolve()
        if not resolved.is_file():
            raise CacheError(f"Deadlock cache does not exist: {resolved}")
        try:
            inferred_account = int(resolved.parents[3].name)
            app_directory = resolved.parents[2]
        except (IndexError, ValueError) as error:
            if account_id is None:
                raise CacheError(
                    "--account-id is required with a nonstandard --cache-path"
                ) from error
            inferred_account = account_id
            app_directory = resolved.parent.parent.parent
        if account_id is not None and inferred_account != account_id:
            raise CacheError(
                f"cache belongs to account {inferred_account}, not requested account {account_id}"
            )
        return CacheLocation(inferred_account, resolved, app_directory)

    roots = (root,) if root is not None else steam_roots()
    candidates: list[CacheLocation] = []
    discovered_paths: set[Path] = set()
    for steam_directory in roots:
        userdata = steam_directory.expanduser() / "userdata"
        for account in _steam_accounts(userdata, account_id):
            candidate = account / DEADLOCK_APP_ID / CACHE_RELATIVE_PATH
            resolved = candidate.resolve(strict=False)
            if candidate.is_file() and resolved not in discovered_paths:
                discovered_paths.add(resolved)
                candidates.append(
                    CacheLocation(
                        account_id=int(account.name),
                        cache_path=resolved,
                        app_directory=(account / DEADLOCK_APP_ID).resolve(),
                    )
                )
    if not candidates:
        requested = f" for account {account_id}" if account_id is not None else ""
        raise CacheError(f"no Deadlock Steam Cloud cache found{requested}")
    if len(candidates) > 1:
        accounts = ", ".join(
            f"{candidate.account_id} at {candidate.cache_path}"
            for candidate in candidates
        )
        hint = (
            "--cache-path"
            if len({candidate.account_id for candidate in candidates}) == 1
            else "--account-id or --cache-path"
        )
        raise CacheError(f"multiple Deadlock caches found ({accounts}); pass {hint}")
    return candidates[0]


def deadlock_is_running() -> bool:
    proc = Path("/proc")
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            command = (
                (entry / "cmdline")
                .read_bytes()
                .replace(b"\0", b" ")
                .decode("utf-8", errors="ignore")
            )
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        lowered = command.casefold()
        if "deadlock.exe" in lowered and (
            "steamapps/common/deadlock" in lowered or "s:\\common\\deadlock" in lowered
        ):
            return True
    return False


def read_cache(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        if raw[:4] == b"\x04\x33\x56\x4b" and len(raw) >= 72:
            compression_method = struct.unpack_from("<I", raw, 20)[0]
            block_count = struct.unpack_from("<I", raw, 56)[0]
            block_total_size = struct.unpack_from("<I", raw, 60)[0]
            if compression_method == 0 and block_count and block_total_size:
                # keyvalues3 0.7 expects uncompressed v4 blob bytes inside the
                # main buffer. ValveResourceFormat and Source 2 store them
                # directly after that buffer. Adapt an in-memory validation
                # copy without changing the on-disk, Source 2-compatible file.
                compatible = bytearray(raw)
                uncompressed_size = struct.unpack_from("<I", compatible, 48)[0]
                compressed_size = struct.unpack_from("<I", compatible, 52)[0]
                struct.pack_into(
                    "<I", compatible, 48, uncompressed_size + block_total_size
                )
                struct.pack_into(
                    "<I", compatible, 52, compressed_size + block_total_size
                )
                document = keyvalues3.read(io.BytesIO(compatible))
            else:
                document = keyvalues3.read(io.BytesIO(raw))
        else:
            document = keyvalues3.read(io.BytesIO(raw))
    except Exception as error:
        raise CacheError(f"could not parse {path}: {error}") from error
    root_value = document.value
    if not isinstance(root_value, dict):
        raise CacheError("Deadlock cache root is not an object")
    root = cast("dict[str, Any]", root_value)
    required = {"LastUsedBuilds", "Favorites", "Unpublished", "SavedLastUsed"}
    if not required.issubset(root):
        missing = ", ".join(sorted(required - set(root)))
        raise CacheError(f"Deadlock cache is missing required sections: {missing}")
    if not isinstance(root["Unpublished"], list):
        raise CacheError("Deadlock cache Unpublished section is not an array")
    return root


def _cached_builds(root: dict[str, Any]) -> list[bytes]:
    blobs: list[bytes] = []
    for section in ("Favorites", "Unpublished", "SavedLastUsed"):
        values = root.get(section, [])
        if not isinstance(values, list):
            continue
        blobs.extend(
            bytes(value) for value in values if isinstance(value, (bytes, bytearray))
        )
    return blobs


def _allocate_local_build_id(root: dict[str, Any], account_id: int) -> int:
    local_ids = []
    for blob in _cached_builds(root):
        try:
            metadata = hero_build_metadata(blob)
        except ValueError:
            continue
        if (
            metadata.author_account_id == account_id
            and metadata.build_id is not None
            and metadata.publish_timestamp in {None, 0}
            and 0 < metadata.build_id < 1000
        ):
            local_ids.append(metadata.build_id)
    build_id = max(local_ids, default=1) + 1
    if build_id >= 1000:
        raise CacheError("no safe local build ID remains below the reserved 1000 range")
    return build_id


def update_managed_builds(
    root: dict[str, Any],
    guides: list[PurchaseGuide],
    *,
    account_id: int,
    persona: str,
    timestamp: int,
    patch_title: str,
    patch_published_at: str,
    rank_range: RankRange = DEFAULT_RANK_RANGE,
) -> tuple[dict[str, Any], dict[int, int], int, int]:
    updated_root = deepcopy(root)
    unpublished = updated_root["Unpublished"]
    build_ids: dict[int, int] = {}
    created = 0
    updated = 0

    for guide in guides:
        managed_index: int | None = None
        managed_id: int | None = None
        for index, blob in enumerate(unpublished):
            if not isinstance(blob, (bytes, bytearray)):
                continue
            try:
                metadata = hero_build_metadata(bytes(blob))
            except ValueError:
                continue
            if is_managed_build(metadata, hero_id=guide.hero_id, account_id=account_id):
                if managed_index is not None:
                    raise CacheError(
                        f"multiple managed builds already exist for {guide.hero_name}; restore or remove duplicates"
                    )
                managed_index = index
                managed_id = metadata.build_id
        if managed_id is None:
            managed_id = _allocate_local_build_id(updated_root, account_id)
        hero_build = encode_hero_build(
            guide,
            build_id=managed_id,
            account_id=account_id,
            persona=persona,
            timestamp=timestamp,
            patch_title=patch_title,
            patch_published_at=patch_published_at,
            rank_range=rank_range,
        )
        wrapped = wrap_hero_build(hero_build)
        if managed_index is None:
            unpublished.append(wrapped)
            created += 1
        else:
            unpublished[managed_index] = wrapped
            updated += 1
        build_ids[guide.hero_id] = managed_id
    return updated_root, build_ids, created, updated


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
    shutil.copy2(location.cache_path, backup / "cached_hero_builds.kv3")
    if location.remote_cache_path.is_file():
        shutil.copy2(location.remote_cache_path, backup / "remotecache.vdf")
    return backup


def _validate_managed_entries(
    root: dict[str, Any],
    expected: dict[int, int],
    *,
    account_id: int,
) -> None:
    found: dict[int, int] = {}
    for blob in root.get("Unpublished", []):
        if not isinstance(blob, (bytes, bytearray)):
            continue
        try:
            metadata = hero_build_metadata(bytes(blob))
        except ValueError:
            continue
        hero_id = metadata.hero_id
        if (
            metadata.author_account_id == account_id
            and hero_id is not None
            and hero_id in expected
            and metadata.description
            and MANAGED_MARKER in metadata.description
        ):
            if hero_id in found:
                raise CacheError(
                    f"replacement cache contains duplicate managed hero {hero_id}"
                )
            if metadata.build_id is None:
                raise CacheError(
                    f"replacement cache managed hero {hero_id} has no build ID"
                )
            found[hero_id] = metadata.build_id
    if found != expected:
        raise CacheError(
            f"replacement cache validation failed: expected {expected}, found {found}"
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
) -> InstallResult:
    if deadlock_is_running():
        raise CacheError(
            "Deadlock is running; close it before installing private builds"
        )
    if not guides:
        raise CacheError("no guides were generated")
    incomplete = [
        guide.hero_name for guide in guides if not guide.has_complete_item_coverage
    ]
    if incomplete:
        raise CacheError(
            "refusing to install guides with incomplete item coverage: "
            + ", ".join(incomplete)
        )

    original = read_cache(location.cache_path)
    replacement, build_ids, created, updated = update_managed_builds(
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
    manifest = {
        "account_id": location.account_id,
        "cache_path": str(location.cache_path),
        "created_at": datetime.now(UTC).isoformat(),
        "build_ids": build_ids,
        "rank_range": rank_range.as_dict(),
    }
    (backup / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".cached_hero_builds.",
            suffix=".tmp",
            dir=location.cache_path.parent,
            delete=False,
        ) as temporary:
            temporary.write(encoded)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        candidate = read_cache(temporary_path)
        _validate_managed_entries(candidate, build_ids, account_id=location.account_id)
        temporary_path.replace(location.cache_path)
        temporary_path = None
        installed = read_cache(location.cache_path)
        _validate_managed_entries(installed, build_ids, account_id=location.account_id)
    except Exception as error:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        try:
            shutil.copy2(backup / "cached_hero_builds.kv3", location.cache_path)
        except Exception as restore_error:
            raise CacheError(
                f"installation failed ({error}) and automatic restore failed ({restore_error}); "
                f"backup is at {backup}"
            ) from restore_error
        if isinstance(error, CacheError):
            raise
        raise CacheError(
            f"installation failed and the original cache was restored: {error}"
        ) from error

    return InstallResult(location.cache_path, backup, build_ids, created, updated)


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
        (backup_root or _state_root())
        / "deadlock-build-sync/backups"
        / str(location.account_id)
    )
    backups = (
        sorted(
            (
                path
                for path in parent.iterdir()
                if (path / "cached_hero_builds.kv3").is_file()
            ),
            reverse=True,
        )
        if parent.is_dir()
        else []
    )
    if not backups:
        raise CacheError(f"no cache backups found for account {location.account_id}")
    source = backups[0] / "cached_hero_builds.kv3"
    read_cache(source)
    temporary = location.cache_path.with_name(".cached_hero_builds.restore.tmp")
    shutil.copy2(source, temporary)
    try:
        read_cache(temporary)
        temporary.replace(location.cache_path)
    finally:
        temporary.unlink(missing_ok=True)
    return backups[0]
