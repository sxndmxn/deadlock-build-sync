from datetime import UTC, datetime
from pathlib import Path

import pytest

from deadlock_build_sync import cache_install, cache_types
from deadlock_build_sync.cache import CacheError, CacheLocation, InstallResult
from deadlock_build_sync.ranks import DEFAULT_RANK_RANGE
from tests.cache_fixtures import SNAPSHOT_ID, complete_guide, snapshot_manifest


def _location(tmp_path: Path) -> CacheLocation:
    app_directory = tmp_path / "userdata/7/1422450"
    cache_path = app_directory / "remote/cfg/cached_hero_builds.kv3"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_bytes(b"original")
    return CacheLocation(7, cache_path, app_directory)


def test_install_reports_running_deadlock_exactly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cache_install, "deadlock_is_running", lambda: True)

    with pytest.raises(
        CacheError,
        match=r"^Deadlock is running; close it before installing private builds$",
    ):
        cache_install.install_guides(
            _location(tmp_path),
            [complete_guide()],
            persona="Player",
            timestamp=100,
            patch_title="Patch",
            patch_published_at="2026-01-01T00:00:00Z",
        )


def test_install_passes_identity_scope_rank_and_result_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    location = _location(tmp_path)
    guide = complete_guide()
    manifest_input = snapshot_manifest()
    backup = tmp_path / "backup"
    identity = cache_types._GuideInstallationIdentity(
        hero_ids={12},
        build_keys={(12, "default")},
        snapshot_id=SNAPSHOT_ID,
        policy_ids={(12, "default"): "policy/kelvin"},
        identities={(12, "default"): (SNAPSHOT_ID, "policy/kelvin")},
    )
    calls: dict[str, object] = {}

    class FixedDatetime:
        @staticmethod
        def now(timezone: object) -> datetime:
            assert timezone is UTC
            return datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)

    def validate_request(
        _guides: object,
        received_manifest: object,
        received_hero_ids: object,
        *,
        allow_subset: bool,
    ) -> cache_types._GuideInstallationIdentity:
        calls["request"] = (
            received_manifest,
            received_hero_ids,
            allow_subset,
        )
        return identity

    def fingerprint(
        _root: dict[str, object],
        *,
        account_id: int,
        target_hero_ids: set[int],
    ) -> str:
        calls["fingerprint"] = (account_id, target_hero_ids)
        return "scope-fingerprint"

    def update(
        _root: dict[str, object],
        _guides: object,
        **options: object,
    ) -> tuple[dict[str, object], dict[tuple[int, str], int], int, int, int]:
        calls["update"] = options
        return {"replacement": True}, {(12, "default"): 34}, 1, 2, 3

    def write_manifest(path: Path, value: dict[str, object]) -> None:
        calls["manifest"] = (path, value)

    def install_replacement(
        received_location: CacheLocation,
        encoded: bytes,
        validation: cache_types._ReplacementValidation,
    ) -> None:
        calls["replacement"] = (received_location, encoded, validation)

    monkeypatch.setattr(cache_install, "datetime", FixedDatetime)
    monkeypatch.setattr(cache_install, "deadlock_is_running", lambda: False)
    monkeypatch.setattr(cache_install, "_validate_install_request", validate_request)
    monkeypatch.setattr(cache_install, "read_cache", lambda _path: {"original": True})
    monkeypatch.setattr(cache_install, "_out_of_scope_fingerprint", fingerprint)
    monkeypatch.setattr(cache_install, "update_managed_builds", update)
    monkeypatch.setattr(cache_install, "encode_binary_v4", lambda _root: b"encoded")
    monkeypatch.setattr(
        cache_install, "_create_backup", lambda *_args, **_kwargs: backup
    )
    monkeypatch.setattr(
        cache_install, "projection_fingerprint", lambda _guide: "projection"
    )
    monkeypatch.setattr(cache_install, "atomic_write_json", write_manifest)
    monkeypatch.setattr(cache_install, "_install_replacement", install_replacement)

    result = cache_install.install_guides(
        location,
        [guide],
        persona="Player",
        timestamp=100,
        patch_title="Patch",
        patch_published_at="2026-01-01T00:00:00Z",
        rank_range=DEFAULT_RANK_RANGE,
        backup_root=tmp_path / "state",
        snapshot_manifest=manifest_input,
        expected_hero_ids={12, 13},
        allow_subset=True,
    )

    assert calls["request"] == (manifest_input, {12, 13}, True)
    assert calls["fingerprint"] == (7, {12})
    update_options = calls["update"]
    assert isinstance(update_options, dict)
    assert update_options == {
        "account_id": 7,
        "persona": "Player",
        "timestamp": 100,
        "patch_title": "Patch",
        "patch_published_at": "2026-01-01T00:00:00Z",
        "rank_range": DEFAULT_RANK_RANGE,
    }
    assert calls["manifest"] == (
        backup / "manifest.json",
        {
            "account_id": 7,
            "cache_path": str(location.cache_path),
            "created_at": "2026-01-02T03:04:05+00:00",
            "builds": [
                {
                    "hero_id": 12,
                    "path_id": "default",
                    "build_id": 34,
                    "policy_id": "policy/kelvin",
                    "projection_fingerprint": "projection",
                }
            ],
            "rank_range": DEFAULT_RANK_RANGE.as_dict(),
            "snapshot": manifest_input,
            "snapshot_id": SNAPSHOT_ID,
            "out_of_scope_sha256": "scope-fingerprint",
        },
    )
    assert calls["replacement"] == (
        location,
        b"encoded",
        cache_types._ReplacementValidation(
            7,
            {(12, "default"): 34},
            identity.identities,
            {12},
            "scope-fingerprint",
        ),
    )
    assert result == InstallResult(
        location.cache_path,
        backup,
        {(12, "default"): 34},
        1,
        2,
        3,
        SNAPSHOT_ID,
        {(12, "default"): "policy/kelvin"},
    )


def test_restore_uses_latest_valid_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    location = _location(tmp_path)
    parent = tmp_path / "state/deadlock-build-sync/backups/7"
    old = parent / "20260101T000000Z"
    latest = parent / "20260102T000000Z"
    ignored = parent / "20260103T000000Z"
    for path in (old, latest, ignored):
        path.mkdir(parents=True)
    (old / "cached_hero_builds.kv3").write_bytes(b"old")
    (latest / "cached_hero_builds.kv3").write_bytes(b"latest")
    calls: list[tuple[Path, Path]] = []
    monkeypatch.setattr(cache_install, "deadlock_is_running", lambda: False)
    monkeypatch.setattr(cache_install, "read_cache", lambda _path: {})
    monkeypatch.setattr(
        cache_install,
        "_restore_cache_file",
        lambda source, destination: calls.append((source, destination)),
    )

    restored = cache_install.restore_latest(location, backup_root=tmp_path / "state")

    assert restored == latest
    assert calls == [(latest / "cached_hero_builds.kv3", location.cache_path)]


def test_restore_reports_running_and_missing_backups_exactly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    location = _location(tmp_path)
    monkeypatch.setattr(cache_install, "deadlock_is_running", lambda: True)
    with pytest.raises(
        CacheError,
        match=r"^Deadlock is running; close it before restoring a cache backup$",
    ):
        cache_install.restore_latest(location, backup_root=tmp_path / "state")

    monkeypatch.setattr(cache_install, "deadlock_is_running", lambda: False)
    with pytest.raises(
        CacheError,
        match=r"^no cache backups found for account 7$",
    ):
        cache_install.restore_latest(location, backup_root=tmp_path / "state")
