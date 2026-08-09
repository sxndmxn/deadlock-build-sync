from datetime import UTC, datetime, timedelta

import pytest

from deadlock_build_sync.api import DeadlockApi
from deadlock_build_sync.ranks import RankCatalog
from deadlock_build_sync.snapshot import (
    EpochBoundary,
    EpochSet,
    EvidenceRecorder,
    EvidenceUnit,
    MatchMode,
    OutcomePolicy,
    SnapshotManifest,
)


def test_recorder_hashes_exact_bytes_and_requires_declared_grain() -> None:
    recorder = EvidenceRecorder()
    recorder.declare(
        "/fixture",
        unit=EvidenceUnit.ASSET,
        backend_grain="fixture-row",
        fallback_behavior="reject",
    )
    compact = recorder.record("/fixture", {"b": 2, "a": 1}, b'{"value":1}')
    spaced = recorder.record("/fixture", {"a": 1, "b": 2}, b'{"value": 1}')

    assert compact.sha256 != spaced.sha256
    assert compact.parameters == {"a": 1, "b": 2}
    assert compact.unit == EvidenceUnit.ASSET
    assert compact.backend_grain == "fixture-row"
    with pytest.raises(ValueError, match="not declared"):
        recorder.record("/unknown", {}, b"{}")


def manifest(*, created_at: str, fetched_at: str) -> SnapshotManifest:
    boundary = EpochBoundary("patch", 100)
    recorder = EvidenceRecorder()
    recorder.declare(
        "/fixture",
        unit=EvidenceUnit.ASSET,
        backend_grain="fixture",
    )
    recorder.record(
        "/fixture",
        {"version": 123},
        b"payload",
        fetched_at=datetime.fromisoformat(fetched_at),
    )
    return SnapshotManifest(
        client_version=123,
        as_of_timestamp=200,
        created_at=created_at,
        match_mode=MatchMode.RANKED,
        game_mode="normal",
        rank_range={"minimum": 91, "maximum": 116},
        rank_labels_sha256="ranks",
        patch={"identity": "patch"},
        epochs=EpochSet(boundary, boundary, boundary, boundary),
        outcome_policy=OutcomePolicy(),
        outcome_policy_enforced=False,
        records=tuple(recorder.records),
    )


def test_snapshot_identity_ignores_wall_clock_but_not_source_or_epoch() -> None:
    first_time = datetime.now(UTC)
    later_time = first_time + timedelta(hours=1)
    first = manifest(
        created_at=first_time.isoformat(),
        fetched_at=first_time.isoformat(),
    )
    later = manifest(
        created_at=later_time.isoformat(),
        fetched_at=later_time.isoformat(),
    )

    assert first.snapshot_id == later.snapshot_id
    assert first.as_dict()["created_at"] != later.as_dict()["created_at"]


def test_patch_identity_uses_guid_and_content_not_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = DeadlockApi()
    rows = [
        {
            "title": "Same title",
            "source": "official",
            "guid": {"id": "new"},
            "pub_date": "2026-08-02T00:00:00Z",
            "link": "https://example.invalid/new",
            "content": {"notes": "new"},
        },
        {
            "title": "Same title",
            "source": "official",
            "guid": {"id": "old"},
            "pub_date": "2026-08-01T00:00:00Z",
            "link": "https://example.invalid/old",
            "content": {"notes": "old"},
        },
    ]
    monkeypatch.setattr(api, "get_json", lambda _path: rows)

    patch = api.current_patch()

    assert patch.title == "Same title"
    assert '"new"' in patch.guid
    assert patch.identity != "Same title"
    assert len(patch.content_sha256) == 64


def test_manifest_rejects_cutoff_before_independent_epoch() -> None:
    rank_catalog = RankCatalog({tier: f"Tier {tier}" for tier in range(1, 12)})
    assert rank_catalog.sha256
    boundary = EpochBoundary("future", 300)
    record = manifest(
        created_at=datetime.now(UTC).isoformat(),
        fetched_at=datetime.now(UTC).isoformat(),
    ).records
    with pytest.raises(ValueError, match="precedes"):
        SnapshotManifest(
            client_version=123,
            as_of_timestamp=200,
            created_at=datetime.now(UTC).isoformat(),
            match_mode=MatchMode.RANKED,
            game_mode="normal",
            rank_range={},
            rank_labels_sha256="ranks",
            patch={},
            epochs=EpochSet(boundary, boundary, boundary, boundary),
            outcome_policy=OutcomePolicy(),
            outcome_policy_enforced=False,
            records=record,
        )
