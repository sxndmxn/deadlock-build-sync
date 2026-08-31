from dataclasses import replace

import pytest

from deadlock_build_sync import cache_projection
from deadlock_build_sync.cache import CacheError
from deadlock_build_sync.presentation import MANAGED_MARKER
from deadlock_build_sync.protobuf import HeroBuildMetadata, hero_build_metadata
from deadlock_build_sync.ranks import Rank, RankDivision, RankRange, RankTier
from tests.cache_fixtures import guide, unpublished


def _metadata(
    *,
    build_id: int | None = 2,
    hero_id: int | None = 12,
    account_id: int | None = 7,
    path_id: str | None = "default",
) -> HeroBuildMetadata:
    path_line = f"\nBuild path: {path_id}." if path_id is not None else ""
    return HeroBuildMetadata(
        build_id,
        hero_id,
        account_id,
        "Build",
        f"{MANAGED_MARKER}{path_line}",
        0,
        None,
        (),
    )


def test_cached_builds_reads_all_three_build_sections_in_order() -> None:
    root: dict[str, object] = {
        "Favorites": [b"favorite"],
        "Unpublished": [bytearray(b"unpublished")],
        "SavedLastUsed": [b"saved"],
    }

    assert cache_projection._cached_builds(root) == [
        b"favorite",
        b"unpublished",
        b"saved",
    ]
    assert cache_projection._cached_builds({}) == []


def test_build_id_allocation_skips_bad_blobs_before_a_valid_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cache_projection,
        "_cached_builds",
        lambda _root: [b"bad", b"valid"],
    )

    def metadata(blob: bytes) -> HeroBuildMetadata:
        if blob == b"bad":
            raise ValueError("bad protobuf")
        return _metadata(build_id=5)

    monkeypatch.setattr(cache_projection, "hero_build_metadata", metadata)

    assert cache_projection._allocate_local_build_id({}, 7) == 6


@pytest.mark.parametrize(("existing_id", "expected"), [(0, 2), (1000, 2)])
def test_build_id_allocation_ignores_reserved_or_nonpositive_ids(
    existing_id: int,
    expected: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cache_projection, "_cached_builds", lambda _root: [b"blob"])
    monkeypatch.setattr(
        cache_projection,
        "hero_build_metadata",
        lambda _blob: _metadata(build_id=existing_id),
    )

    assert cache_projection._allocate_local_build_id({}, 7) == expected


def test_build_id_allocation_reports_the_reserved_limit_exactly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cache_projection, "_cached_builds", lambda _root: [b"blob"])
    monkeypatch.setattr(
        cache_projection,
        "hero_build_metadata",
        lambda _blob: _metadata(build_id=999),
    )

    with pytest.raises(
        CacheError,
        match=r"^no safe local build ID remains below the reserved 1000 range$",
    ):
        cache_projection._allocate_local_build_id({}, 7)


def test_target_managed_build_rejects_missing_hero_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cache_projection,
        "try_hero_build_metadata",
        lambda _blob: _metadata(hero_id=None),
    )

    assert (
        cache_projection._target_managed_build(
            b"blob",
            target_hero_ids={12},
            account_id=7,
        )
        is None
    )


def test_managed_scan_continues_past_retained_and_stale_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = {
        "plain": None,
        "stale": (12, _metadata(build_id=3, path_id="stale")),
        "missing-path": (12, _metadata(build_id=5, path_id=None)),
        "desired": (12, _metadata(build_id=4)),
    }
    monkeypatch.setattr(
        cache_projection,
        "_target_managed_build",
        lambda blob, **_kwargs: values[blob],
    )

    scan = cache_projection._scan_managed_builds(
        ["plain", "stale", "missing-path", "desired"],
        desired={(12, "default")},
        account_id=7,
    )

    assert scan.retained == ["plain"]
    assert scan.existing_ids == {(12, "default"): 4}
    assert scan.removed_candidates == 3


def test_managed_scan_ignores_a_managed_marker_without_a_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cache_projection,
        "_target_managed_build",
        lambda _blob, **_kwargs: (12, _metadata(path_id=None)),
    )

    scan = cache_projection._scan_managed_builds(
        ["missing-path"],
        desired={(12, "default")},
        account_id=7,
    )

    assert scan.retained == []
    assert scan.existing_ids == {}
    assert scan.removed_candidates == 1


def test_managed_scan_reports_duplicate_hero_and_path_exactly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cache_projection,
        "_target_managed_build",
        lambda _blob, **_kwargs: (12, _metadata()),
    )

    with pytest.raises(
        CacheError,
        match=(r"^multiple or malformed managed builds already exist for 12/default$"),
    ):
        cache_projection._scan_managed_builds(
            ["first", "second"],
            desired={(12, "default")},
            account_id=7,
        )


def test_managed_update_allocates_sequential_ids_for_the_requested_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    def allocate(_root: dict[str, object], account_id: int) -> int:
        calls.append(account_id)
        return 2

    monkeypatch.setattr(cache_projection, "_allocate_local_build_id", allocate)
    first = replace(guide(), path_id="control", policy_id="policy/control")
    second = replace(guide(), path_id="damage", policy_id="policy/damage")

    _, build_ids, created, updated, removed = cache_projection.update_managed_builds(
        {"Unpublished": []},
        [first, second],
        account_id=7,
        persona="Player",
        timestamp=100,
        patch_title="Patch",
        patch_published_at="2026-01-01T00:00:00Z",
    )

    assert calls == [7]
    assert build_ids == {(12, "control"): 2, (12, "damage"): 3}
    assert (created, updated, removed) == (2, 0, 0)


def test_managed_update_counts_multiple_existing_builds() -> None:
    control = replace(guide(), path_id="control", policy_id="policy/control")
    damage = replace(guide(), path_id="damage", policy_id="policy/damage")
    first, _, _, _, _ = cache_projection.update_managed_builds(
        {"Unpublished": []},
        [control, damage],
        account_id=7,
        persona="Player",
        timestamp=100,
        patch_title="Patch",
        patch_published_at="2026-01-01T00:00:00Z",
    )

    second, _, created, updated, removed = cache_projection.update_managed_builds(
        first,
        [control, damage],
        account_id=7,
        persona="Player",
        timestamp=200,
        patch_title="Patch",
        patch_published_at="2026-01-01T00:00:00Z",
    )

    assert (created, updated, removed) == (0, 2, 0)
    assert len(unpublished(second)) == 2


def test_managed_update_passes_a_custom_rank_range_to_presentation() -> None:
    rank_range = RankRange(
        Rank(RankTier.INITIATE, RankDivision.ONE),
        Rank(RankTier.SEEKER, RankDivision.TWO),
    )

    updated, _, _, _, _ = cache_projection.update_managed_builds(
        {"Unpublished": []},
        [guide()],
        account_id=7,
        persona="Player",
        timestamp=100,
        patch_title="Patch",
        patch_published_at="2026-01-01T00:00:00Z",
        rank_range=rank_range,
    )

    blob = unpublished(updated)[0]
    assert isinstance(blob, bytes)
    assert "Initiate I–Seeker II" in (hero_build_metadata(blob).description or "")
