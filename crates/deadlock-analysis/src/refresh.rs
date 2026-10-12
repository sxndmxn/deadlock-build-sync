use std::fs::{File, OpenOptions};

use deadlock_data::{Error, Result, atomic_write_json, read_json, text, trace_operation};
use deadlock_guides::HERO_BUILD_METHOD;
use deadlock_input::parse_patch_feed;
use serde_json::json;

use crate::extraction::extract_cohort;
use crate::refresh_configuration::{
    Cohort, RANK_RESET_AT, RefreshRequest, RunPaths, cohort_ranks, implementation_record,
    parse_timestamp,
};
use crate::sources::{capture_sources, validate_source_fingerprints};

/// An extracted run and the lock that keeps other processes from changing it.
#[derive(Debug)]
pub struct ExtractedRun {
    pub paths: RunPaths,
    _lock: File,
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
        .open(paths.run.join(".refresh.lock"))?;
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
    let manifest = read_json(&paths.run.join("manifest.json"))?;
    if manifest["schema_version"] != 2
        || manifest["test_usage"] != "reserved"
        || manifest["extraction"]
            .as_object()
            .is_none_or(serde_json::Map::is_empty)
        || !paths.raw.join("analysis.duckdb").is_file()
    {
        return Err(Error::new(
            "Resume requires a completed production source extraction",
        ));
    }
    if cohort_ranks(&manifest["cohort"])? != request.ranks {
        return Err(Error::new("Resume requires matching source ranks"));
    }
    for (name, requested) in [("since", request.since), ("as_of", request.as_of)] {
        if let Some(requested) = requested
            && requested != parse_timestamp(text(&manifest["cohort"], name)?)?
        {
            return Err(Error::new(
                "Resume timestamps must match the source snapshot",
            ));
        }
    }
    validate_source_fingerprints(paths, &manifest["sources"])
}

fn capture_run(paths: &RunPaths, request: &RefreshRequest) -> Result<()> {
    let manifest_path = paths.run.join("manifest.json");
    if manifest_path.exists() {
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
    cohort.validate()?;
    let mut manifest = json!({"schema_version":2,"cohort":cohort.to_document()?,"sources":sources,
        "production_method":HERO_BUILD_METHOD,"implementation":implementation_record(),"test_usage":"reserved"});
    atomic_write_json(&manifest_path, &manifest)?;
    manifest["extraction"] = extract_cohort(paths, &cohort, request.extraction_resources)?;
    atomic_write_json(&manifest_path, &manifest)
}
