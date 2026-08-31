from __future__ import annotations

import io
import struct
from copy import deepcopy
from typing import TYPE_CHECKING, cast

import keyvalues3

from .presentation import build_presentation
from .protobuf import (
    HeroBuildMetadata,
    encode_hero_build,
    hero_build_metadata,
    is_managed_build,
    managed_build_path,
    wrap_hero_build,
)
from .ranks import DEFAULT_RANK_RANGE
from .value_validation import object_list

if TYPE_CHECKING:
    from pathlib import Path

    from .purchase_guide import PurchaseGuide
    from .ranks import RankRange


from .cache_types import (
    BuildKey,
    CacheError,
    _ManagedBuildScan,
)


def read_cache(path: Path) -> dict[str, object]:
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
    root = cast("dict[str, object]", root_value)
    required = {"LastUsedBuilds", "Favorites", "Unpublished", "SavedLastUsed"}
    if not required.issubset(root):
        missing = ", ".join(sorted(required - set(root)))
        raise CacheError(f"Deadlock cache is missing required sections: {missing}")
    if not isinstance(root["Unpublished"], list):
        raise CacheError("Deadlock cache Unpublished section is not an array")
    return root


def _cached_builds(root: dict[str, object]) -> list[bytes]:
    blobs: list[bytes] = []
    for section in ("Favorites", "Unpublished", "SavedLastUsed"):
        values = root.get(section, [])
        if not isinstance(values, list):
            continue
        blobs.extend(
            bytes(value) for value in values if isinstance(value, (bytes, bytearray))
        )
    return blobs


def _allocate_local_build_id(root: dict[str, object], account_id: int) -> int:
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


def _target_managed_build(
    blob: object,
    *,
    target_hero_ids: set[int],
    account_id: int,
) -> HeroBuildMetadata | None:
    if not isinstance(blob, (bytes, bytearray)):
        return None
    try:
        metadata = hero_build_metadata(bytes(blob))
    except ValueError:
        return None
    hero_id = metadata.hero_id
    if hero_id not in target_hero_ids or not is_managed_build(
        metadata,
        hero_id=cast("int", hero_id),
        account_id=account_id,
    ):
        return None
    return metadata


def _scan_managed_builds(
    unpublished: list[object],
    *,
    desired: set[BuildKey],
    account_id: int,
) -> _ManagedBuildScan:
    target_hero_ids = {build_key[0] for build_key in desired}
    existing_ids: dict[BuildKey, int] = {}
    retained: list[object] = []
    removed_candidates = 0
    for blob in unpublished:
        metadata = _target_managed_build(
            blob,
            target_hero_ids=target_hero_ids,
            account_id=account_id,
        )
        if metadata is None:
            retained.append(blob)
            continue
        removed_candidates += 1
        path_id = managed_build_path(metadata)
        key = (cast("int", metadata.hero_id), path_id) if path_id is not None else None
        if key is None or key not in desired:
            continue
        if key in existing_ids or metadata.build_id is None:
            raise CacheError(
                f"multiple or malformed managed builds already exist for {key[0]}/{key[1]}"
            )
        existing_ids[key] = metadata.build_id
    return _ManagedBuildScan(retained, existing_ids, removed_candidates)


def update_managed_builds(
    root: dict[str, object],
    guides: list[PurchaseGuide],
    *,
    account_id: int,
    persona: str,
    timestamp: int,
    patch_title: str,
    patch_published_at: str,
    rank_range: RankRange = DEFAULT_RANK_RANGE,
) -> tuple[dict[str, object], dict[BuildKey, int], int, int, int]:
    updated_root = deepcopy(root)
    unpublished = object_list(updated_root["Unpublished"])
    if unpublished is None:
        raise CacheError("Deadlock cache Unpublished section is not an array")
    desired = {(guide.hero_id, guide.path_id) for guide in guides}
    scan = _scan_managed_builds(
        unpublished,
        desired=desired,
        account_id=account_id,
    )
    updated_root["Unpublished"] = scan.retained
    unpublished = scan.retained
    build_ids: dict[BuildKey, int] = {}
    created = 0
    updated = 0
    next_new_id = _allocate_local_build_id(root, account_id)

    for guide in guides:
        key = guide.hero_id, guide.path_id
        managed_id = scan.existing_ids.get(key)
        if managed_id is None:
            managed_id = next_new_id
            next_new_id += 1
            if managed_id >= 1000:
                raise CacheError(
                    "no safe local build ID remains below the reserved 1000 range"
                )
        hero_build = encode_hero_build(
            build_presentation(
                guide,
                persona=persona,
                patch_title=patch_title,
                patch_published_at=patch_published_at,
                rank_range=rank_range,
            ),
            build_id=managed_id,
            account_id=account_id,
            timestamp=timestamp,
        )
        wrapped = wrap_hero_build(hero_build)
        unpublished.append(wrapped)
        if key not in scan.existing_ids:
            created += 1
        else:
            updated += 1
        build_ids[key] = managed_id
    removed = scan.removed_candidates - updated
    return updated_root, build_ids, created, updated, removed
