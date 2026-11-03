use std::path::{Path, PathBuf};

use deadlock_data::{Error, Result, state_directory};
use deadlock_steam::{CacheLocation, CacheSearch, discover_cache};

use crate::cli_arguments::LocationArguments;

pub fn home_directory() -> Result<PathBuf> {
    std::env::var_os("HOME")
        .filter(|value| !value.is_empty())
        .map(PathBuf::from)
        .filter(|path| path.is_absolute())
        .ok_or_else(|| Error::new("Cannot determine the user home directory"))
}

pub fn absolute_path(path: &Path) -> Result<PathBuf> {
    let expanded = if path == Path::new("~") {
        home_directory()?
    } else if let Ok(relative) = path.strip_prefix("~/") {
        home_directory()?.join(relative)
    } else {
        path.to_path_buf()
    };
    if expanded.try_exists()? {
        Ok(expanded.canonicalize()?)
    } else {
        Ok(std::path::absolute(expanded)?)
    }
}

pub fn artifact_directory(configured: Option<&Path>) -> Result<PathBuf> {
    configured.map_or_else(|| Ok(state_directory()?.join("artifacts")), absolute_path)
}

pub fn cache_location(arguments: &LocationArguments) -> Result<CacheLocation> {
    discover_cache(
        &CacheSearch {
            account_id: arguments.account_id,
            cache_path: arguments
                .cache_path
                .as_deref()
                .map(absolute_path)
                .transpose()?,
        },
        &home_directory()?,
    )
}
