use std::collections::BTreeSet;
use std::fs;
use std::path::{Path, PathBuf};

use deadlock_data::{Error, Result};

use crate::cache_location::{APPLICATION_ID, CACHE_RELATIVE_PATH, CacheLocation, CacheSearch};

const STEAM_ROOTS: [&str; 5] = [
    ".local/share/Steam",
    ".steam/steam",
    ".steam/root",
    ".var/app/com.valvesoftware.Steam/.local/share/Steam",
    "snap/steam/common/.local/share/Steam",
];

/// # Errors
/// Returns an error when an existing Steam directory cannot be resolved.
pub fn steam_roots(home: &Path) -> Result<Vec<PathBuf>> {
    let mut roots = Vec::new();
    let mut seen = BTreeSet::new();
    for relative in STEAM_ROOTS {
        let candidate = home.join(relative);
        if candidate.try_exists()? {
            let canonical = candidate.canonicalize()?;
            if canonical.is_dir() && seen.insert(canonical.clone()) {
                roots.push(canonical);
            }
        }
    }
    Ok(roots)
}

/// # Errors
/// Returns an error when no cache matches, multiple caches match, or the account does not match.
pub fn discover_cache(search: &CacheSearch, home: &Path) -> Result<CacheLocation> {
    if search.account_id == Some(0) {
        return Err(Error::new("Steam account ID must be positive"));
    }
    if let Some(path) = &search.cache_path {
        return explicit_location(path, search.account_id);
    }
    let roots = match &search.steam_root {
        Some(root) => vec![root.clone()],
        None => steam_roots(home)?,
    };
    let mut candidates = Vec::new();
    let mut seen = BTreeSet::new();
    for root in roots {
        for (account_id, account) in accounts(&root.join("userdata"), search.account_id)? {
            let app_directory = account.join(APPLICATION_ID);
            let cache_path = app_directory.join(CACHE_RELATIVE_PATH);
            if cache_path.is_file() {
                let cache_path = cache_path.canonicalize()?;
                if seen.insert(cache_path.clone()) {
                    candidates.push(CacheLocation {
                        account_id,
                        cache_path,
                        app_directory: app_directory.canonicalize()?,
                    });
                }
            }
        }
    }
    select_location(candidates)
}

fn accounts(userdata: &Path, selected: Option<u32>) -> Result<Vec<(u32, PathBuf)>> {
    if let Some(account) = selected {
        return Ok(vec![(account, userdata.join(account.to_string()))]);
    }
    if !userdata.try_exists()? {
        return Ok(Vec::new());
    }
    let mut accounts = Vec::new();
    for entry in fs::read_dir(userdata)? {
        let entry = entry?;
        if let Some(account) = entry
            .file_name()
            .to_str()
            .and_then(|name| name.parse::<u32>().ok())
            && account != 0
            && entry.path().is_dir()
        {
            accounts.push((account, entry.path()));
        }
    }
    accounts.sort_unstable();
    Ok(accounts)
}

fn explicit_location(path: &Path, selected: Option<u32>) -> Result<CacheLocation> {
    let cache_path = path
        .canonicalize()
        .map_err(|error| Error::new(format!("Cannot resolve cache {}: {error}", path.display())))?;
    if !cache_path.is_file() {
        return Err(Error::new("Steam cache path must be a regular file"));
    }
    let app_directory = cache_path
        .ancestors()
        .nth(3)
        .ok_or_else(|| Error::new("Steam cache path has no application directory"))?
        .to_path_buf();
    let inferred = infer_account(&app_directory);
    let account_id = selected
        .or(inferred)
        .filter(|account| *account != 0)
        .ok_or_else(|| Error::new("A nonstandard cache path requires --account-id"))?;
    if inferred.is_some_and(|account| account != account_id) {
        return Err(Error::new(
            "Steam cache account does not match --account-id",
        ));
    }
    Ok(CacheLocation {
        account_id,
        cache_path,
        app_directory,
    })
}

fn infer_account(app_directory: &Path) -> Option<u32> {
    if app_directory.file_name()? != APPLICATION_ID {
        return None;
    }
    app_directory.parent()?.file_name()?.to_str()?.parse().ok()
}

fn select_location(mut candidates: Vec<CacheLocation>) -> Result<CacheLocation> {
    if candidates.len() > 1 {
        let descriptions = candidates
            .iter()
            .map(|location| {
                format!(
                    "{} at {}",
                    location.account_id,
                    location.cache_path.display()
                )
            })
            .collect::<Vec<_>>()
            .join(", ");
        return Err(Error::new(format!(
            "Multiple Steam caches match: {descriptions}. Set --account-id or --cache-path"
        )));
    }
    candidates
        .pop()
        .ok_or_else(|| Error::new("No Deadlock Steam cache matches the request"))
}
