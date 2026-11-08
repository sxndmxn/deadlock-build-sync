use std::fs;
use std::path::Path;
use std::time::{Duration, SystemTime};

use deadlock_analysis::{
    CohortRecord, EXTRACTION_SQL_SHA256, ExtractionRecord, ExtractionResources,
    MANIFEST_SCHEMA_VERSION, RefreshRequest, RunManifest, RunPaths, SOURCE_FILES, SourceRecord,
    extract_run,
};
use deadlock_data::{Error, RankRange, Result, atomic_write_json, fingerprint};
use serde_json::{Value, json};

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
    check_changed_extraction_sql(&request, &paths, &manifest)?;
    atomic_write_json(&paths.manifest(), &manifest)?;
    drop(extract_run(&request)?);
    if fs::read(paths.database())? != b"extraction marker" {
        return Err(Error::new("Resume changed the extracted database"));
    }
    check_run_removal(root.path())
}

/// Removal must keep the current run, named runs, locked runs, and new runs.
/// It must remove old automatic runs with or without an unlocked lock file.
fn check_run_removal(root: &Path) -> Result<()> {
    let results = root.join("results");
    for name in [
        "20261001T000000Z",
        "20261002T000000Z",
        "20261005T000000Z",
        "named-run",
    ] {
        fs::create_dir_all(results.join(name).join("raw"))?;
    }
    for name in ["20261003T000000Z", "20261006T000000Z"] {
        fs::create_dir_all(results.join(name))?;
        fs::File::create(results.join(name).join(".refresh.lock"))?;
    }
    let lock = fs::File::open(results.join("20261003T000000Z").join(".refresh.lock"))?;
    lock.lock()?;
    let two_hours_ago = SystemTime::now() - Duration::from_secs(7200);
    for name in [
        "20261001T000000Z",
        "20261002T000000Z",
        "20261003T000000Z",
        "20261006T000000Z",
    ] {
        fs::File::open(results.join(name))?.set_modified(two_hours_ago)?;
    }
    let mut request = create_request(root);
    request.run_id = Some("20261004T000000Z".into());
    create_snapshot(&RunPaths::create(root, request.run_id.as_deref())?)?;
    let removed = extract_run(&request)?.remove_other_automatic_runs();
    drop(lock);
    let mut remaining = fs::read_dir(&results)?
        .map(|entry| Ok(entry?.file_name().to_string_lossy().into_owned()))
        .collect::<Result<Vec<_>>>()?;
    remaining.sort();
    if removed != 3
        || remaining
            != [
                "20261003T000000Z",
                "20261004T000000Z",
                "20261005T000000Z",
                "named-run",
                "reference",
            ]
    {
        return Err(Error::new(format!(
            "Run removal removed {removed} runs and kept {remaining:?}"
        )));
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

/// Writes a complete run manifest and returns it as JSON for the malformed cases.
fn create_snapshot(paths: &RunPaths) -> Result<Value> {
    let ranks = RankRange::default();
    let document = json!({"reference":1});
    let mut source_sha256 = std::collections::BTreeMap::new();
    for name in SOURCE_FILES {
        atomic_write_json(&paths.raw.join(name), &document)?;
        source_sha256.insert(name.to_owned(), fingerprint(&document)?);
    }
    let manifest = RunManifest {
        schema_version: MANIFEST_SCHEMA_VERSION,
        cohort: CohortRecord {
            minimum_badge: ranks.minimum.badge(),
            maximum_badge: ranks.maximum.badge(),
            since: "2026-10-10T00:00:00Z".into(),
            as_of: "2026-10-11T00:00:00Z".into(),
            match_mode: "Ranked".into(),
            game_mode: "Normal".into(),
        },
        sources: SourceRecord {
            client_version: 1,
            active_heroes: 1,
            shop_items: 1,
            source_sha256,
        },
        extraction: Some(ExtractionRecord {
            player_matches: 100,
            match_folds: 100,
            purchases: 100,
            heroes: 1,
            source_snapshot_version: 1,
        }),
        extraction_sql_sha256: Some(EXTRACTION_SQL_SHA256.into()),
    };
    manifest.write(paths)?;
    fs::write(paths.database(), b"extraction marker")?;
    Ok(serde_json::to_value(manifest)?)
}

/// A run extracted with other SQL cannot be resumed. A run without the fingerprint can.
fn check_changed_extraction_sql(
    request: &RefreshRequest,
    paths: &RunPaths,
    manifest: &Value,
) -> Result<()> {
    let mut changed = manifest.clone();
    changed["extraction_sql_sha256"] = json!("0".repeat(64));
    atomic_write_json(&paths.manifest(), &changed)?;
    require_rejection(request, "changed extraction SQL")?;
    let mut unknown = manifest.clone();
    unknown
        .as_object_mut()
        .ok_or_else(|| Error::new("Reference manifest is not an object"))?
        .remove("extraction_sql_sha256");
    atomic_write_json(&paths.manifest(), &unknown)?;
    drop(extract_run(request)?);
    Ok(())
}

fn check_invalid_fingerprints(
    request: &RefreshRequest,
    paths: &RunPaths,
    manifest: &Value,
) -> Result<()> {
    for hashes in [Value::Null, json!({}), json!([])] {
        let mut invalid = manifest.clone();
        invalid["sources"]["source_sha256"] = hashes;
        atomic_write_json(&paths.manifest(), &invalid)?;
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
        atomic_write_json(&paths.manifest(), &invalid)?;
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
        atomic_write_json(&paths.manifest(), &invalid)?;
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
