use std::fs::{File, OpenOptions, TryLockError};
use std::io::ErrorKind;
use std::path::Path;
use std::time::Duration;

use deadlock_data::{Error, Result, parse_timestamp, read_json, trace_operation};
use deadlock_input::parse_patch_feed;

use crate::extraction::extract_cohort;
use crate::refresh_configuration::{
    Cohort, RANK_RESET_AT, RefreshRequest, RunPaths, is_automatic_run_id,
};
use crate::run_manifest::{EXTRACTION_SQL_SHA256, MANIFEST_SCHEMA_VERSION, RunManifest};
use crate::sources::{capture_sources, validate_source_fingerprints};

const RUN_LOCK_FILE: &str = ".refresh.lock";
const UNLOCKED_RUN_MINIMUM_AGE: Duration = Duration::from_secs(3600);

/// An extracted run and the lock that keeps other processes from changing it.
#[derive(Debug)]
pub struct ExtractedRun {
    pub paths: RunPaths,
    _lock: File,
}

impl ExtractedRun {
    /// Removes the other runs whose identifier has the automatic format, and returns their count.
    ///
    /// Runs with another identifier stay. A run that another process locks stays.
    /// A run that changed in the last hour stays.
    /// A failed removal prints a warning, because the build itself is complete.
    #[must_use]
    pub fn remove_other_automatic_runs(&self) -> usize {
        let Some(results) = self.paths.run.parent() else {
            return 0;
        };
        let entries = match std::fs::read_dir(results) {
            Ok(entries) => entries,
            Err(error) => {
                eprintln!("Warning: Cannot read analysis runs: {error}");
                return 0;
            }
        };
        let mut removed = 0;
        for entry in entries {
            let path = match entry {
                Ok(entry) => entry.path(),
                Err(error) => {
                    eprintln!("Warning: Cannot read analysis runs: {error}");
                    continue;
                }
            };
            if path.file_name() == self.paths.run.file_name()
                || !path
                    .file_name()
                    .and_then(|name| name.to_str())
                    .is_some_and(is_automatic_run_id)
            {
                continue;
            }
            match remove_unlocked_run(&path) {
                Ok(true) => removed += 1,
                Ok(false) => (),
                Err(error) if error.kind() == ErrorKind::NotFound => (),
                Err(error) => eprintln!(
                    "Warning: Cannot remove analysis run {}: {error}",
                    path.display()
                ),
            }
        }
        removed
    }
}

/// Removes a run directory unless another process can own it, and returns whether it removed it.
///
/// A new run creates its directory, then its lock file, and then it locks the file.
/// Thus a run that changed in the last hour stays, also when nothing locks it.
fn remove_unlocked_run(path: &Path) -> std::io::Result<bool> {
    let metadata = std::fs::symlink_metadata(path)?;
    if !metadata.is_dir()
        || metadata.modified()?.elapsed().unwrap_or_default() < UNLOCKED_RUN_MINIMUM_AGE
    {
        return Ok(false);
    }
    let lock_path = path.join(RUN_LOCK_FILE);
    let lock = match std::fs::symlink_metadata(&lock_path) {
        Ok(lock) if lock.is_file() => {
            let lock = File::open(lock_path)?;
            match lock.try_lock() {
                Ok(()) => Some(lock),
                Err(TryLockError::WouldBlock) => return Ok(false),
                Err(TryLockError::Error(error)) => return Err(error),
            }
        }
        Ok(_) => return Err(std::io::Error::other("The run lock is not a regular file")),
        Err(error) if error.kind() == ErrorKind::NotFound => None,
        Err(error) => return Err(error),
    };
    std::fs::remove_dir_all(path)?;
    drop(lock);
    Ok(true)
}

/// Captures sources and extracts the cohort, or reuses a completed extraction with `resume`.
///
/// # Errors
/// Returns an error when source capture, snapshot identity, or extraction fails.
pub fn extract_run(request: &RefreshRequest) -> Result<ExtractedRun> {
    if request.resume && request.run_id.is_none() {
        return Err(Error::new("Resume requires --run-id."));
    }
    request.extraction_resources.validate()?;
    request.ranks.validate()?;
    let paths = RunPaths::create(&request.root, request.run_id.as_deref())?;
    let lock = OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(paths.run.join(RUN_LOCK_FILE))?;
    lock.try_lock()
        .map_err(|error| Error::new(format!("Analysis run is locked: {error}")))?;
    if request.resume {
        validate_resume(&paths, request)?;
    } else {
        capture_run(&paths, request)?;
    }
    Ok(ExtractedRun { paths, _lock: lock })
}

fn validate_resume(paths: &RunPaths, request: &RefreshRequest) -> Result<()> {
    let manifest = RunManifest::read(paths)?;
    if manifest.schema_version != MANIFEST_SCHEMA_VERSION
        || manifest.extraction.is_none()
        || !paths.database().is_file()
    {
        return Err(Error::new(
            "Resume requires a completed production source extraction",
        ));
    }
    if manifest
        .extraction_sql_sha256
        .as_deref()
        .is_some_and(|recorded| recorded != EXTRACTION_SQL_SHA256)
    {
        return Err(Error::new(
            "Resume requires the extraction SQL of the run. Use a new --run-id",
        ));
    }
    if manifest.cohort.ranks()? != request.ranks {
        return Err(Error::new("Resume requires matching source ranks"));
    }
    for (recorded, requested) in [
        (&manifest.cohort.since, request.since),
        (&manifest.cohort.as_of, request.as_of),
    ] {
        if let Some(requested) = requested
            && requested != parse_timestamp(recorded)?
        {
            return Err(Error::new(
                "Resume timestamps must match the source snapshot",
            ));
        }
    }
    validate_source_fingerprints(paths, &manifest.sources)
}

fn capture_run(paths: &RunPaths, request: &RefreshRequest) -> Result<()> {
    if paths.manifest().exists() {
        return Err(Error::new(
            "Use a new --run-id to preserve the previous source snapshot",
        ));
    }
    let as_of = request
        .as_of
        .unwrap_or_else(|| chrono::Utc::now().timestamp());
    let sources = trace_operation("analysis.capture_sources", Some("capture_sources"), || {
        capture_sources(paths, &request.api_base_url)
    })?;
    let patch = parse_patch_feed(&read_json(&paths.raw.join("patches.json"))?, Some(as_of))?;
    // An explicit --since can start before the latest feed post, because the
    // feed also lists posts without balance changes, such as hero releases.
    let since = request
        .since
        .unwrap_or(patch.start_timestamp)
        .max(parse_timestamp(RANK_RESET_AT)?);
    let cohort = Cohort {
        ranks: request.ranks,
        since,
        as_of,
    };
    let mut manifest = RunManifest {
        schema_version: MANIFEST_SCHEMA_VERSION,
        cohort: cohort.record()?,
        sources,
        extraction: None,
        extraction_sql_sha256: Some(EXTRACTION_SQL_SHA256.into()),
    };
    manifest.write(paths)?;
    manifest.extraction = Some(extract_cohort(
        paths,
        &cohort,
        request.extraction_resources,
    )?);
    manifest.write(paths)
}
