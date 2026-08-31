"""Safe discovery, projection, validation, and installation of Steam builds."""

from .cache_discovery import (
    deadlock_is_running,
    discover_cache,
    steam_root,
    steam_roots,
)
from .cache_install import install_guides, restore_latest
from .cache_projection import read_cache, update_managed_builds
from .cache_storage import _fsync_directory
from .cache_types import (
    CACHE_RELATIVE_PATH,
    DEADLOCK_APP_ID,
    STEAM_ROOT_RELATIVE_PATHS,
    BuildKey,
    CacheError,
    CacheLocation,
    InstallResult,
)

__all__ = [
    "CACHE_RELATIVE_PATH",
    "DEADLOCK_APP_ID",
    "STEAM_ROOT_RELATIVE_PATHS",
    "BuildKey",
    "CacheError",
    "CacheLocation",
    "InstallResult",
    "_fsync_directory",
    "deadlock_is_running",
    "discover_cache",
    "install_guides",
    "read_cache",
    "restore_latest",
    "steam_root",
    "steam_roots",
    "update_managed_builds",
]
