from __future__ import annotations

import io
import struct
from copy import deepcopy
from typing import TYPE_CHECKING

import keyvalues3

from .presentation import build_presentation
from .protobuf import (
    HeroBuildMetadata,
    encode_hero_build,
    is_managed_build,
    managed_build_path,
    parse_hero_build_metadata,
    try_parse_hero_build_metadata,
    wrap_hero_build,
)
from .ranks import DEFAULT_RANK_RANGE
from .value_validation import object_dict, object_list

if TYPE_CHECKING:
    from pathlib import Path

    from .purchase_guide import PurchaseGuide
    from .ranks import RankRange


from .cache_types import (
    BuildKey,
    CacheError,
    _ManagedBuildScan,
)

_KV3_V4_MAGIC = b"\x04\x33\x56\x4b"
_UINT32_FORMAT = "<I"


def read_cache(path: Path) -> dict[str, object]:
    try:
        raw = path.read_bytes()
        if raw[:4] == _KV3_V4_MAGIC and len(raw) >= 72:
            compression_method = struct.unpack_from(_UINT32_FORMAT, raw, 20)[0]
            block_count = struct.unpack_from(_UINT32_FORMAT, raw, 56)[0]
            block_total_size = struct.unpack_from(_UINT32_FORMAT, raw, 60)[0]
            if compression_method == 0 and block_count and block_total_size:
                # keyvalues3 0.7 expects uncompressed v4 blob bytes inside the
                # main buffer. ValveResourceFormat and Source 2 store them
                # directly after that buffer. Adapt an in-memory validation
                # copy without changing the on-disk, Source 2-compatible file.
                compatible = bytearray(raw)
                uncompressed_size = struct.unpack_from(_UINT32_FORMAT, compatible, 48)[
                    0
                ]
                compressed_size = struct.unpack_from(_UINT32_FORMAT, compatible, 52)[0]
                struct.pack_into(
                    _UINT32_FORMAT,
                    compatible,
                    48,
                    uncompressed_size + block_total_size,
                )
                struct.pack_into(
                    _UINT32_FORMAT,
                    compatible,
                    52,
                    compressed_size + block_total_size,
                )
                document = keyvalues3.read(io.BytesIO(compatible))
            else:
                document = keyvalues3.read(io.BytesIO(raw))
        else:
            document = keyvalues3.read(io.BytesIO(raw))
    except Exception as error:
        raise CacheError(f"could not parse {path}: {error}") from error
    root = object_dict(document.value)
    if root is None:
        raise CacheError("Deadlock cache root is not an object")
    required = {"LastUsedBuilds", "Favorites", "Unpublished", "SavedLastUsed"}
    if not required.issubset(root):
        missing = ", ".join(sorted(required - set(root)))
        raise CacheError(f"Deadlock cache is missing required sections: {missing}")
    if not isinstance(root["Unpublished"], list):
        raise CacheError("Deadlock cache Unpublished section is not an array")
    return root


def _read_cached_builds(root: dict[str, object]) -> list[bytes]:
    blobs: list[bytes] = []
    for section in ("Favorites", "Unpublished", "SavedLastUsed"):
        values = root.get(section)
        if not isinstance(values, list):
            continue
        blobs.extend(
            bytes(value) for value in values if isinstance(value, (bytes, bytearray))
        )
    return blobs


def _allocate_local_build_id(root: dict[str, object], account_id: int) -> int:
    local_ids = []
    for blob in _read_cached_builds(root):
        try:
            metadata = parse_hero_build_metadata(blob)
        except ValueError:
            continue
        if (
            metadata.author_account_id == account_id
            and metadata.build_id is not None
            and metadata.publish_timestamp in {None, 0}
            and metadata.build_id < 1000
        ):
            local_ids.append(metadata.build_id)
    build_id = max([1, *local_ids]) + 1
    if build_id >= 1000:
        raise CacheError("no safe local build ID remains below the reserved 1000 range")
    return build_id


def _match_target_managed_build(
    blob: object,
    *,
    target_hero_ids: set[int],
    account_id: int,
) -> tuple[int, HeroBuildMetadata] | None:
    metadata = try_parse_hero_build_metadata(blob)
    if metadata is None:
        return None
    hero_id = metadata.hero_id
    if (
        hero_id is None
        or hero_id not in target_hero_ids
        or not is_managed_build(
            metadata,
            hero_id=hero_id,
            account_id=account_id,
        )
    ):
        return None
    return hero_id, metadata


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
        target = _match_target_managed_build(
            blob,
            target_hero_ids=target_hero_ids,
            account_id=account_id,
        )
        if target is None:
            retained.append(blob)
            continue
        hero_id, metadata = target
        removed_candidates += 1
        path_id = managed_build_path(metadata)
        if path_id is None:
            continue
        key = hero_id, path_id
        if key not in desired:
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
