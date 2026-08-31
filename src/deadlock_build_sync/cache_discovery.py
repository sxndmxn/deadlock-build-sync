from __future__ import annotations

from pathlib import Path

from .cache_types import (
    CACHE_RELATIVE_PATH,
    DEADLOCK_APP_ID,
    STEAM_ROOT_RELATIVE_PATHS,
    CacheError,
    CacheLocation,
)


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


def _steam_accounts(userdata: Path, account_id: int | None) -> list[Path]:
    if account_id is not None:
        return [userdata / str(account_id)]
    if not userdata.is_dir():
        return []
    return [
        path for path in userdata.iterdir() if path.is_dir() and path.name.isdigit()
    ]


def _explicit_cache_location(
    cache_path: Path,
    account_id: int | None,
) -> CacheLocation:
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
            f"cache belongs to account {inferred_account}, not requested account "
            f"{account_id}"
        )
    return CacheLocation(inferred_account, resolved, app_directory)


def _discover_cache_locations(
    roots: tuple[Path, ...],
    account_id: int | None,
) -> list[CacheLocation]:
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
    return candidates


def _select_cache_location(
    candidates: list[CacheLocation],
    account_id: int | None,
) -> CacheLocation:
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


def discover_cache(
    *,
    account_id: int | None = None,
    cache_path: Path | None = None,
    root: Path | None = None,
) -> CacheLocation:
    if cache_path is not None:
        return _explicit_cache_location(cache_path, account_id)
    roots = (root,) if root is not None else steam_roots()
    return _select_cache_location(
        _discover_cache_locations(roots, account_id), account_id
    )


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
