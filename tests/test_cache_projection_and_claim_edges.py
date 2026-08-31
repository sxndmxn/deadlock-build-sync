import io
import struct
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from deadlock_build_sync import cache_projection
from deadlock_build_sync.cache import CacheError, update_managed_builds
from deadlock_build_sync.policy import ClaimClass, EvidenceClaim, PolicyError
from deadlock_build_sync.protobuf import HeroBuildMetadata
from deadlock_build_sync.snapshot import EvidenceUnit
from tests.cache_fixtures import guide, unpublished


@dataclass
class _Document:
    value: object


def _managed_blob() -> bytes:
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
        persona="Player",
        timestamp=100,
        patch_title="Patch",
        patch_published_at="2026-01-01T00:00:00Z",
    )
    blob = unpublished(updated)[0]
    assert isinstance(blob, bytes)
    return blob


def _claim() -> EvidenceClaim:
    return EvidenceClaim(
        claim_id="claim/1",
        claim_class=ClaimClass.DESCRIPTIVE,
        snapshot_id="snapshot",
        cohort={"mode": "ranked"},
        unit=EvidenceUnit.ELIGIBLE_APPEARANCE,
        support=10,
        mechanics_refs=("item/1",),
        language_ceiling=frozenset({"observed"}),
        numerator=5,
        denominator=10,
        estimate=0.5,
        interval=(0.4, 0.6),
    )


def test_cache_reader_wraps_io_and_validates_root_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(CacheError, match="could not parse"):
        cache_projection.read_cache(tmp_path / "missing")

    path = tmp_path / "cache.kv3"
    path.write_bytes(b"fixture")
    monkeypatch.setattr(
        cache_projection.keyvalues3,
        "read",
        lambda _stream: _Document([]),
    )
    with pytest.raises(
        CacheError,
        match=r"^Deadlock cache root is not an object$",
    ):
        cache_projection.read_cache(path)

    monkeypatch.setattr(
        cache_projection.keyvalues3,
        "read",
        lambda _stream: _Document({"Unpublished": []}),
    )
    with pytest.raises(
        CacheError,
        match=(
            r"^Deadlock cache is missing required sections: "
            r"Favorites, LastUsedBuilds, SavedLastUsed$"
        ),
    ):
        cache_projection.read_cache(path)

    malformed: dict[str, object] = {
        "LastUsedBuilds": {},
        "Favorites": [],
        "Unpublished": {},
        "SavedLastUsed": [],
    }
    monkeypatch.setattr(
        cache_projection.keyvalues3,
        "read",
        lambda _stream: _Document(malformed),
    )
    with pytest.raises(
        CacheError,
        match=r"^Deadlock cache Unpublished section is not an array$",
    ):
        cache_projection.read_cache(path)


def test_cache_reader_adapts_only_external_v4_blob_layout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = {
        "LastUsedBuilds": {},
        "Favorites": [],
        "Unpublished": [],
        "SavedLastUsed": [],
    }
    captured: list[bytes] = []

    def read(stream: io.BytesIO) -> _Document:
        captured.append(stream.read())
        return _Document(root)

    monkeypatch.setattr(cache_projection.keyvalues3, "read", read)

    external = bytearray(72)
    external[:4] = b"\x04\x33\x56\x4b"
    external[24] = 1
    struct.pack_into("<I", external, 20, 0)
    struct.pack_into("<I", external, 48, 10)
    struct.pack_into("<I", external, 52, 20)
    struct.pack_into("<I", external, 56, 1)
    struct.pack_into("<I", external, 60, 256)
    compatible = bytearray(external)
    struct.pack_into("<I", compatible, 48, 266)
    struct.pack_into("<I", compatible, 52, 276)

    nonmagic = bytearray(external)
    nonmagic[:4] = b"nope"
    compressed = bytearray(external)
    struct.pack_into("<I", compressed, 20, 1)
    no_blocks = bytearray(external)
    struct.pack_into("<I", no_blocks, 56, 0)
    no_blob_bytes = bytearray(external)
    struct.pack_into("<I", no_blob_bytes, 60, 0)

    cases = [
        (external, compatible),
        (nonmagic, nonmagic),
        (compressed, compressed),
        (no_blocks, no_blocks),
        (no_blob_bytes, no_blob_bytes),
    ]
    for index, (raw, expected) in enumerate(cases):
        path = tmp_path / f"cache-{index}.kv3"
        path.write_bytes(raw)
        assert cache_projection.read_cache(path) == root
        assert captured[-1] == bytes(expected)


def test_cached_build_scan_skips_nonlist_sections() -> None:
    assert cache_projection._cached_builds({
        "Favorites": {},
        "Unpublished": [bytearray(b"one")],
        "SavedLastUsed": ["not-bytes"],
    }) == [b"one"]


def test_build_id_allocation_rejects_reserved_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cache_projection, "_cached_builds", lambda _root: [b"blob"])
    monkeypatch.setattr(
        cache_projection,
        "hero_build_metadata",
        lambda _blob: HeroBuildMetadata(999, 12, 7, None, None, None, 0, ()),
    )

    with pytest.raises(
        CacheError,
        match=r"^no safe local build ID remains below the reserved 1000 range$",
    ):
        cache_projection._allocate_local_build_id({}, 7)


def test_build_id_allocation_ignores_another_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cache_projection, "_cached_builds", lambda _root: [b"blob"])
    monkeypatch.setattr(
        cache_projection,
        "hero_build_metadata",
        lambda _blob: HeroBuildMetadata(10, 12, 8, None, None, None, 0, ()),
    )

    assert cache_projection._allocate_local_build_id({}, 7) == 2


def test_target_managed_build_ignores_bad_values() -> None:
    assert (
        cache_projection._target_managed_build(
            "not-bytes", target_hero_ids={12}, account_id=7
        )
        is None
    )
    assert (
        cache_projection._target_managed_build(
            b"\xff", target_hero_ids={12}, account_id=7
        )
        is None
    )


def test_managed_scan_rejects_duplicate_existing_builds() -> None:
    blob = _managed_blob()

    with pytest.raises(CacheError, match="multiple or malformed managed builds"):
        cache_projection._scan_managed_builds(
            [blob, blob],
            desired={(12, "default")},
            account_id=146293212,
        )


def test_managed_scan_retains_a_non_target_blob() -> None:
    blob = _managed_blob()

    scan = cache_projection._scan_managed_builds(
        [blob],
        desired={(13, "default")},
        account_id=146293212,
    )

    assert scan.retained == [blob]


def test_managed_update_rejects_bad_section_and_reserved_new_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(
        CacheError,
        match=r"^Deadlock cache Unpublished section is not an array$",
    ):
        update_managed_builds(
            {"Unpublished": {}},
            [guide()],
            account_id=7,
            persona="Player",
            timestamp=1,
            patch_title="Patch",
            patch_published_at="2026-01-01T00:00:00Z",
        )

    monkeypatch.setattr(
        cache_projection, "_allocate_local_build_id", lambda *_args: 1000
    )
    with pytest.raises(
        CacheError,
        match=r"^no safe local build ID remains below the reserved 1000 range$",
    ):
        update_managed_builds(
            {"Unpublished": []},
            [guide()],
            account_id=7,
            persona="Player",
            timestamp=1,
            patch_title="Patch",
            patch_published_at="2026-01-01T00:00:00Z",
        )


def test_evidence_claim_rejects_each_invalid_contract() -> None:
    claim = _claim()
    with pytest.raises(PolicyError, match="identity must not be empty"):
        replace(claim, claim_id="")
    with pytest.raises(PolicyError, match="has no cohort"):
        replace(claim, cohort={})
    with pytest.raises(PolicyError, match="negative support"):
        replace(claim, support=-1, denominator=-1)
    with pytest.raises(PolicyError, match="language ceiling"):
        replace(claim, language_ceiling=frozenset({"causes"}))
    with pytest.raises(PolicyError, match="has no mechanics refs"):
        replace(
            claim,
            claim_class=ClaimClass.MECHANICAL,
            mechanics_refs=(),
            language_ceiling=frozenset({"grants"}),
            numerator=None,
            denominator=None,
            estimate=None,
            interval=None,
        )
    with pytest.raises(PolicyError, match=r"quantitative claim.*has no support"):
        replace(claim, support=0, denominator=0)
    with pytest.raises(PolicyError, match="inverted interval"):
        replace(claim, interval=(0.6, 0.4))
    with pytest.raises(PolicyError, match="denominator differs"):
        replace(claim, denominator=9)
