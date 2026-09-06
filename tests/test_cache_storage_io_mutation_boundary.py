import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from deadlock_build_sync import cache_storage
from deadlock_build_sync.cache import CacheError
from tests.cache_fixtures import isolated_location


def _validation() -> cache_storage._ReplacementValidation:
    return cache_storage._ReplacementValidation(
        account_id=146293212,
        build_ids={},
        identities={(12, "default"): ("snapshot", "policy")},
        hero_ids={12},
        out_of_scope_sha256="fingerprint",
    )


def test_backup_uses_utc_timestamp_and_sequential_suffixes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    location, _ = isolated_location(tmp_path)
    location.remote_cache_path.write_text("remote", encoding="utf-8")

    class FixedDatetime:
        @staticmethod
        def now(timezone: object) -> datetime:
            assert timezone is UTC
            return datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)

    monkeypatch.setattr(cache_storage, "datetime", FixedDatetime)

    backups = [
        cache_storage._create_backup(location, root=tmp_path / "state")
        for _index in range(3)
    ]

    assert [path.name for path in backups] == [
        "20260102T030405Z",
        "20260102T030405Z-1",
        "20260102T030405Z-2",
    ]
    assert all((path / "cached_hero_builds.kv3").is_file() for path in backups)
    assert all((path / "remotecache.vdf").is_file() for path in backups)
    assert all(
        "remotecache.vdf" in {entry.name for entry in path.iterdir()}
        for path in backups
    )


def test_directory_fsync_uses_directory_flags_and_always_closes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []

    def open_file(path: Path, flags: int) -> int:
        calls.append(("open", (path, flags)))
        return 23

    def fsync(descriptor: int) -> None:
        calls.append(("fsync", descriptor))

    def close(descriptor: int) -> None:
        calls.append(("close", descriptor))

    monkeypatch.setattr(cache_storage.os, "open", open_file)
    monkeypatch.setattr(cache_storage.os, "fsync", fsync)
    monkeypatch.setattr(cache_storage.os, "close", close)

    cache_storage._fsync_directory(tmp_path)

    assert calls == [
        (
            "open",
            (tmp_path, os.O_RDONLY | cache_storage._O_DIRECTORY),
        ),
        ("fsync", 23),
        ("close", 23),
    ]

    calls.clear()

    def failed_fsync(descriptor: int) -> None:
        calls.append(("fsync", descriptor))
        raise OSError("fsync failed")

    monkeypatch.setattr(cache_storage.os, "fsync", failed_fsync)
    with pytest.raises(OSError, match="fsync failed"):
        cache_storage._fsync_directory(tmp_path)
    assert calls[-1] == ("close", 23)


def test_restore_uses_a_local_persistent_temporary_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    location, _ = isolated_location(tmp_path)
    source = tmp_path / "backup.kv3"
    source.write_bytes(b"backup")
    calls: list[dict[str, object]] = []
    original = tempfile.NamedTemporaryFile

    def named_temporary_file(
        *,
        prefix: str,
        suffix: str,
        dir: Path,  # ruff: ignore[builtin-argument-shadowing]
        delete: bool,
    ) -> object:
        calls.append({
            "prefix": prefix,
            "suffix": suffix,
            "dir": dir,
            "delete": delete,
        })
        return original(prefix=prefix, suffix=suffix, dir=dir, delete=delete)

    monkeypatch.setattr(
        cache_storage.tempfile, "NamedTemporaryFile", named_temporary_file
    )
    monkeypatch.setattr(cache_storage, "read_cache", lambda _path: {})
    monkeypatch.setattr(cache_storage, "_fsync_directory", lambda _path: None)

    cache_storage._restore_cache_file(source, location.cache_path)

    assert calls == [
        {
            "prefix": ".cached_hero_builds.restore.",
            "suffix": ".tmp",
            "dir": location.cache_path.parent,
            "delete": False,
        }
    ]
    assert location.cache_path.read_bytes() == b"backup"


def test_restore_preserves_the_first_error_if_temporary_creation_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    location, _ = isolated_location(tmp_path)

    def fail(**_kwargs: object) -> object:
        raise OSError("temporary creation failed")

    monkeypatch.setattr(cache_storage.tempfile, "NamedTemporaryFile", fail)

    with pytest.raises(OSError, match=r"^temporary creation failed$"):
        cache_storage._restore_cache_file(tmp_path / "backup", location.cache_path)


def test_restore_cleanup_allows_a_missing_temporary_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    location, _ = isolated_location(tmp_path)
    source = tmp_path / "backup.kv3"
    source.write_bytes(b"backup")

    def reject(path: Path) -> dict[str, object]:
        path.unlink()
        raise CacheError("invalid temporary cache")

    monkeypatch.setattr(cache_storage, "read_cache", reject)

    with pytest.raises(CacheError, match=r"^invalid temporary cache$"):
        cache_storage._restore_cache_file(source, location.cache_path)


def test_replacement_validation_passes_expected_identities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validation = _validation()
    calls: list[dict[tuple[int, str], tuple[str, str]] | None] = []

    def validate_entries(
        _root: dict[str, object],
        _expected: dict[tuple[int, str], int],
        *,
        account_id: int,
        identities: dict[tuple[int, str], tuple[str, str]] | None = None,
    ) -> None:
        assert account_id == validation.account_id
        calls.append(identities)

    monkeypatch.setattr(cache_storage, "_validate_managed_entries", validate_entries)
    monkeypatch.setattr(
        cache_storage,
        "_out_of_scope_fingerprint",
        lambda _root, **_kwargs: "fingerprint",
    )

    cache_storage._validate_replacement_cache({}, validation, "scope changed")

    assert calls == [validation.identities]


def test_install_replacement_uses_local_temp_and_both_scope_messages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    location, _ = isolated_location(tmp_path)
    calls: list[dict[str, object]] = []
    scopes: list[str] = []
    original = tempfile.NamedTemporaryFile

    def named_temporary_file(
        *,
        prefix: str,
        suffix: str,
        dir: Path,  # ruff: ignore[builtin-argument-shadowing]
        delete: bool,
    ) -> object:
        calls.append({
            "prefix": prefix,
            "suffix": suffix,
            "dir": dir,
            "delete": delete,
        })
        return original(prefix=prefix, suffix=suffix, dir=dir, delete=delete)

    def validate(
        _root: dict[str, object],
        _validation_value: cache_storage._ReplacementValidation,
        scope_error: str,
    ) -> None:
        scopes.append(scope_error)

    monkeypatch.setattr(
        cache_storage.tempfile, "NamedTemporaryFile", named_temporary_file
    )
    monkeypatch.setattr(cache_storage, "read_cache", lambda _path: {})
    monkeypatch.setattr(cache_storage, "_validate_replacement_cache", validate)
    monkeypatch.setattr(cache_storage, "deadlock_is_running", lambda: False)
    monkeypatch.setattr(cache_storage, "_fsync_directory", lambda _path: None)

    cache_storage._install_replacement(location, b"replacement", _validation())

    assert calls == [
        {
            "prefix": ".cached_hero_builds.",
            "suffix": ".tmp",
            "dir": location.cache_path.parent,
            "delete": False,
        }
    ]
    assert scopes == [
        "replacement cache changed out-of-scope Steam data",
        "installed cache changed out-of-scope Steam data",
    ]
    assert location.cache_path.read_bytes() == b"replacement"


def test_install_replacement_preserves_temporary_creation_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    location, _ = isolated_location(tmp_path)

    def fail(**_kwargs: object) -> object:
        raise OSError("temporary creation failed")

    monkeypatch.setattr(cache_storage.tempfile, "NamedTemporaryFile", fail)

    with pytest.raises(OSError, match=r"^temporary creation failed$"):
        cache_storage._install_replacement(location, b"value", _validation())


def test_install_replacement_cleanup_allows_a_missing_temporary_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    location, _ = isolated_location(tmp_path)

    def reject(path: Path) -> dict[str, object]:
        path.unlink()
        raise CacheError("invalid replacement")

    monkeypatch.setattr(cache_storage, "read_cache", reject)

    with pytest.raises(CacheError, match=r"^invalid replacement$"):
        cache_storage._install_replacement(location, b"value", _validation())


def test_install_replacement_reports_a_late_deadlock_start_exactly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    location, _ = isolated_location(tmp_path)
    monkeypatch.setattr(cache_storage, "read_cache", lambda _path: {})
    monkeypatch.setattr(
        cache_storage,
        "_validate_replacement_cache",
        lambda *_args: None,
    )
    monkeypatch.setattr(cache_storage, "deadlock_is_running", lambda: True)

    with pytest.raises(
        CacheError,
        match=(r"^Deadlock started before replacement; refusing to change the cache$"),
    ):
        cache_storage._install_replacement(location, b"value", _validation())
