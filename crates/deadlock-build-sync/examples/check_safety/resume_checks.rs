use std::fs;
use std::path::Path;

use deadlock_analysis::{ExtractionResources, RefreshRequest, RunPaths, extract_run};
use deadlock_data::{Error, RankRange, Result, atomic_write_json, fingerprint};
use serde_json::{Value, json};

const SOURCE_FILES: [&str; 7] = [
    "client_versions.json",
    "heroes.json",
    "items-all.json",
    "items.json",
    "ranks.json",
    "patches.json",
    "openapi.json",
];

pub fn check_resume_sources() -> Result<()> {
    let root = tempfile::tempdir()?;
    let request = create_request(root.path());
    let paths = RunPaths::create(root.path(), request.run_id.as_deref())?;
    let manifest = create_snapshot(&paths)?;
    drop(extract_run(&request)?);
    for name in SOURCE_FILES {
        let path = paths.raw.join(name);
        fs::write(&path, "{\n  \"reference\": 1\n}\n")?;
        drop(extract_run(&request)?);
        atomic_write_json(&path, &json!({"reference":2}))?;
        require_rejection(&request, name)?;
        fs::write(&path, b"malformed JSON")?;
        require_rejection(&request, name)?;
        fs::remove_file(&path)?;
        require_rejection(&request, name)?;
        atomic_write_json(&path, &json!({"reference":1}))?;
    }
    check_invalid_fingerprints(&request, &paths, &manifest)?;
    atomic_write_json(&paths.run.join("manifest.json"), &manifest)?;
    drop(extract_run(&request)?);
    if fs::read(paths.raw.join("analysis.duckdb"))? != b"extraction marker" {
        return Err(Error::new("Resume changed the extracted database"));
    }
    Ok(())
}

fn create_request(root: &Path) -> RefreshRequest {
    RefreshRequest {
        root: root.into(),
        run_id: Some("reference".into()),
        since: None,
        as_of: None,
        ranks: RankRange::default(),
        extraction_resources: ExtractionResources {
            memory_limit_mb: 64,
            threads: 1,
        },
        resume: true,
        api_base_url: "http://127.0.0.1:1".into(),
    }
}

fn create_snapshot(paths: &RunPaths) -> Result<Value> {
    let ranks = RankRange::default();
    let document = json!({"reference":1});
    let mut hashes = serde_json::Map::new();
    for name in SOURCE_FILES {
        atomic_write_json(&paths.raw.join(name), &document)?;
        hashes.insert(name.into(), fingerprint(&document)?.into());
    }
    let manifest = json!({
        "schema_version":2,
        "test_usage":"reserved",
        "extraction":{"player_matches":100},
        "cohort":{
            "minimum_badge":ranks.minimum.badge(),
            "maximum_badge":ranks.maximum.badge(),
            "since":"2026-10-10T00:00:00Z",
            "as_of":"2026-10-11T00:00:00Z",
        },
        "sources":{"source_sha256":hashes},
    });
    atomic_write_json(&paths.run.join("manifest.json"), &manifest)?;
    fs::write(paths.raw.join("analysis.duckdb"), b"extraction marker")?;
    Ok(manifest)
}

fn check_invalid_fingerprints(
    request: &RefreshRequest,
    paths: &RunPaths,
    manifest: &Value,
) -> Result<()> {
    for hashes in [Value::Null, json!({}), json!([])] {
        let mut invalid = manifest.clone();
        invalid["sources"]["source_sha256"] = hashes;
        atomic_write_json(&paths.run.join("manifest.json"), &invalid)?;
        require_rejection(request, "missing fingerprint map")?;
    }
    for value in [
        Value::Null,
        json!(1),
        json!("invalid"),
        json!("A".repeat(64)),
    ] {
        let mut invalid = manifest.clone();
        invalid["sources"]["source_sha256"]["heroes.json"] = value;
        atomic_write_json(&paths.run.join("manifest.json"), &invalid)?;
        require_rejection(request, "malformed fingerprint")?;
    }
    for replace_name in [false, true] {
        let mut invalid = manifest.clone();
        let hashes = invalid["sources"]["source_sha256"]
            .as_object_mut()
            .ok_or_else(|| Error::new("Reference fingerprints are missing"))?;
        if replace_name {
            hashes.remove("heroes.json");
        }
        hashes.insert("../outside.json".into(), fingerprint(&json!({}))?.into());
        atomic_write_json(&paths.run.join("manifest.json"), &invalid)?;
        require_rejection(request, "unexpected source name")?;
    }
    Ok(())
}

fn require_rejection(request: &RefreshRequest, case: &str) -> Result<()> {
    if extract_run(request).is_ok() {
        return Err(Error::new(format!("Resume accepted {case}")));
    }
    Ok(())
}
