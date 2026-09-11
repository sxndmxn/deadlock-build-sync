from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DEADLOCK_APP_ID = "1422450"
CACHE_RELATIVE_PATH = Path("remote/cfg/cached_hero_builds.kv3")
_CACHE_FILENAME = "cached_hero_builds.kv3"
type BuildKey = tuple[int, str]
STEAM_ROOT_RELATIVE_PATHS = (
    Path(".local/share/Steam"),
    Path(".steam/steam"),
    Path(".steam/root"),
    Path(".var/app/com.valvesoftware.Steam/.local/share/Steam"),
    Path("snap/steam/common/.local/share/Steam"),
)


class CacheError(RuntimeError):
    """Raised when the Deadlock build cache cannot be safely changed."""


class _CacheReplacementError(CacheError):
    """Identify a failure after cache replacement."""


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
    build_ids: dict[BuildKey, int]
    created: int
    updated: int
    removed: int
    snapshot_id: str
    policy_ids: dict[BuildKey, str]


@dataclass(frozen=True)
class _ManagedBuildScan:
    retained: list[object]
    existing_ids: dict[BuildKey, int]
    removed_candidates: int


@dataclass(frozen=True)
class _GuideInstallationIdentity:
    hero_ids: set[int]
    build_keys: set[BuildKey]
    snapshot_id: str
    policy_ids: dict[BuildKey, str]
    identities: dict[BuildKey, tuple[str, str]]


@dataclass(frozen=True)
class _ReplacementValidation:
    account_id: int
    build_ids: dict[BuildKey, int]
    identities: dict[BuildKey, tuple[str, str]]
    hero_ids: set[int]
    out_of_scope_sha256: str
