from pathlib import Path

import pytest

from deadlock_build_sync import cache_discovery
from deadlock_build_sync.cache import CacheError, CacheLocation, discover_cache
from tests.cache_fixtures import create_discoverable_cache


class _Command:
    def __init__(self, payload: bytes = b"", error: OSError | None = None) -> None:
        self.payload = payload
        self.error = error

    def read_bytes(self) -> bytes:
        if self.error is not None:
            raise self.error
        return self.payload


class _Process:
    def __init__(self, name: str, command: _Command) -> None:
        self.name = name
        self.command = command

    def __truediv__(self, name: str) -> _Command:
        assert name == "cmdline"
        return self.command


class _Proc:
    def __init__(self, entries: list[_Process]) -> None:
        self.entries = entries

    def iterdir(self) -> list[_Process]:
        return self.entries


def test_steam_root_selects_an_existing_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing = tmp_path / "missing"
    existing = tmp_path / "existing"
    existing.mkdir()
    monkeypatch.setattr(cache_discovery, "steam_roots", lambda: (missing, existing))

    assert cache_discovery.steam_root() == existing


def test_steam_root_uses_the_first_candidate_when_none_exist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots = (tmp_path / "first", tmp_path / "second")
    monkeypatch.setattr(cache_discovery, "steam_roots", lambda: roots)

    assert cache_discovery.steam_root() == roots[0]


def test_account_scan_handles_explicit_and_missing_userdata(tmp_path: Path) -> None:
    userdata = tmp_path / "userdata"

    assert cache_discovery._find_steam_accounts(userdata, 12) == [userdata / "12"]
    assert cache_discovery._find_steam_accounts(userdata, None) == []

    userdata.mkdir()
    numeric_directory = userdata / "12"
    numeric_directory.mkdir()
    (userdata / "34").touch()
    (userdata / "words").mkdir()
    assert cache_discovery._find_steam_accounts(userdata, None) == [numeric_directory]


def test_explicit_cache_path_checks_file_account_and_layout(tmp_path: Path) -> None:
    with pytest.raises(CacheError, match="does not exist"):
        discover_cache(cache_path=tmp_path / "missing")

    root = tmp_path / "Steam"
    path = create_discoverable_cache(root, 146293212)
    location = discover_cache(cache_path=path, account_id=146293212)
    assert location == CacheLocation(146293212, path.resolve(), path.parents[2])

    with pytest.raises(CacheError, match="not requested account"):
        discover_cache(cache_path=path, account_id=99)

    nonstandard = tmp_path / "custom/cache.kv3"
    nonstandard.parent.mkdir()
    nonstandard.touch()
    with pytest.raises(
        CacheError,
        match=r"^--account-id is required with a nonstandard --cache-path$",
    ):
        discover_cache(cache_path=nonstandard)

    inferred = discover_cache(cache_path=nonstandard, account_id=77)
    assert inferred == CacheLocation(77, nonstandard.resolve(), nonstandard.parents[2])


def test_location_scan_filters_account_files_and_duplicate_paths(
    tmp_path: Path,
) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    expected = create_discoverable_cache(first_root, 11).resolve()
    create_discoverable_cache(first_root, 22)
    duplicate = second_root / "userdata/11"
    duplicate.parent.mkdir(parents=True)
    duplicate.symlink_to(first_root / "userdata/11", target_is_directory=True)

    locations = cache_discovery._discover_cache_locations(
        (first_root, second_root),
        11,
    )

    assert locations == [CacheLocation(11, expected, expected.parents[2])]
    assert discover_cache(root=first_root, account_id=11) == locations[0]

    with pytest.raises(
        CacheError,
        match=r"^no Deadlock Steam Cloud cache found for account 99$",
    ):
        discover_cache(root=tmp_path / "missing", account_id=99)


def test_multiple_accounts_request_an_account_or_exact_path(tmp_path: Path) -> None:
    first = create_discoverable_cache(tmp_path / "first", 11)
    second = create_discoverable_cache(tmp_path / "second", 22)
    candidates = [
        CacheLocation(11, first, first.parents[2]),
        CacheLocation(22, second, second.parents[2]),
    ]

    with pytest.raises(
        CacheError,
        match=(
            r"^multiple Deadlock caches found \(11 at .*, 22 at .*\); "
            r"pass --account-id or --cache-path$"
        ),
    ):
        cache_discovery._select_cache_location(candidates, None)

    same_account = [candidates[0], CacheLocation(11, second, second.parents[2])]
    with pytest.raises(CacheError, match=r"pass --cache-path$"):
        cache_discovery._select_cache_location(same_account, 11)

    with pytest.raises(
        CacheError,
        match=r"^no Deadlock Steam Cloud cache found for account 99$",
    ):
        cache_discovery._select_cache_location([], 99)
    with pytest.raises(
        CacheError,
        match=r"^no Deadlock Steam Cloud cache found$",
    ):
        cache_discovery._select_cache_location([], None)


def test_deadlock_process_scan_skips_noise_and_detects_linux_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = _Proc([
        _Process("self", _Command()),
        _Process("10", _Command(error=PermissionError("denied"))),
        _Process("11", _Command(b"other-game")),
        _Process(
            "12",
            _Command(b"/games/steamapps/common/Deadlock/game/bin/win64/deadlock.exe"),
        ),
    ])
    requested_paths: list[object] = []

    def path(value: object) -> _Proc:
        requested_paths.append(value)
        return proc

    monkeypatch.setattr(cache_discovery, "Path", path)

    assert cache_discovery.deadlock_is_running()
    assert requested_paths == ["/proc"]


def test_deadlock_process_scan_returns_false_without_matching_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = _Proc([
        _Process("12", _Command(b"deadlock.exe from another directory")),
        _Process("13", _Command(b"S:\\common\\other\\deadlock.exe")),
    ])
    monkeypatch.setattr(cache_discovery, "Path", lambda _path: proc)

    assert not cache_discovery.deadlock_is_running()


def test_deadlock_process_scan_supports_windows_paths_and_bad_utf8(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = _Proc([
        _Process(
            "12",
            _Command(b"\xffS:\\common\\Deadlock\\game\\bin\\deadlock.exe"),
        )
    ])
    monkeypatch.setattr(cache_discovery, "Path", lambda _path: proc)

    assert cache_discovery.deadlock_is_running()
