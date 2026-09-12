use std::fs::OpenOptions;
use std::path::PathBuf;

use deadlock_data::{Error, Result, atomic_write_json, read_json, text, trace_operation};
use deadlock_guides::{BuildGenerator, CURRENT_METHOD_VERSION, beam_generator_record};
use deadlock_input::parse_patch_feed;
use serde_json::json;

use crate::config::{
    Cohort, RANK_RESET_AT, RefreshRequest, RunPaths, cohort_ranks, implementation_record,
    parse_timestamp,
};
use crate::extraction::extract_cohort;
use crate::production_evidence::export_evidence;
use crate::sources::capture_sources;

#[derive(Clone, Debug)]
pub struct RefreshResult {
    pub artifact_id: String,
    pub output: PathBuf,
    pub run_directory: PathBuf,
}

/// # Errors
/// Returns an error when source capture, snapshot identity, analysis, or complete artifact validation fails.
pub fn refresh_evidence(request: &RefreshRequest) -> Result<RefreshResult> {
    if request.workers == 0 || (request.resume && request.run_id.is_none()) {
        return Err(Error::new(
            "Refresh requires positive workers. Resume requires --run-id.",
        ));
    }
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
    let document = export_evidence(
        &paths,
        &request.output,
        request.workers,
        request.resume,
        request.generator,
        &request.api_base_url,
    )?;
    Ok(RefreshResult {
        artifact_id: text(&document, "artifact_id")?.into(),
        output: request.output.clone(),
        run_directory: paths.run,
    })
}

fn validate_resume(paths: &RunPaths, request: &RefreshRequest) -> Result<()> {
    let manifest = read_json(&paths.run.join("manifest.json"))?;
    let generator = manifest["generator"].as_str().unwrap_or("current");
    if manifest["schema_version"] != 2
        || manifest["production_method"] != "eclat_leiden_pairwise"
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
    if manifest["method_version"] != CURRENT_METHOD_VERSION
        || manifest["implementation"] != implementation_record()
    {
        return Err(Error::new(
            "Source extraction implementation differs. Start a new --run-id.",
        ));
    }
    if generator != request.generator.as_str()
        || manifest["rank_expansion"] != serde_json::to_value(request.rank_expansion)?
        || cohort_ranks(&manifest["cohort"])? != request.ranks
    {
        return Err(Error::new(
            "Resume generator and ranks must match the source snapshot",
        ));
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
    Ok(())
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
    let since = request
        .since
        .unwrap_or(parse_timestamp(RANK_RESET_AT)?)
        .max(patch.start_timestamp);
    let cohort = Cohort {
        ranks: request.ranks,
        since,
        as_of,
    };
    cohort.validate()?;
    let mut manifest = json!({"schema_version":2,"rank_expansion":request.rank_expansion,"cohort":cohort.to_document()?,"sources":sources,
        "production_method":"eclat_leiden_pairwise","method_version":CURRENT_METHOD_VERSION,"implementation":implementation_record(),"test_usage":"reserved"});
    if request.generator == BuildGenerator::Beam {
        manifest["generator"] = "beam".into();
        manifest["beam_resume"] =
            json!({"generator":beam_generator_record()?,"implementation":implementation_record()});
    }
    atomic_write_json(&manifest_path, &manifest)?;
    manifest["extraction"] = extract_cohort(paths, &cohort, request.rank_expansion)?;
    atomic_write_json(&manifest_path, &manifest)
}
