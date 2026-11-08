use std::path::Path;
use std::sync::atomic::{AtomicUsize, Ordering};

use deadlock_data::{
    Error, Result, array, fingerprint, format_timestamp, integer, read_json, trace_operation,
};
use duckdb::types::{TimeUnit, Value as SqlValue};
use serde::Deserialize;
use serde_json::{Value, json};

use crate::database::{AnalysisDatabase, Parameters};
use crate::refresh_configuration::{Cohort, DUCKLAKE_URL, ExtractionResources, RunPaths};
use crate::run_manifest::ExtractionRecord;
use crate::sql_resources::sql;

/// 64 threads read one day of remote rows 3.8 times faster than 8 threads, at equal bytes.
const REMOTE_READ_THREADS: u16 = 64;
/// The server sends one file at about 10 to 15 MB/s, so the download reads 16 files at a time.
const REMOTE_DOWNLOAD_CONNECTIONS: usize = 16;

#[derive(Debug, Deserialize)]
struct RemoteFile {
    data_file: String,
}

pub fn extract_cohort(
    paths: &RunPaths,
    cohort: &Cohort,
    resources: ExtractionResources,
) -> Result<ExtractionRecord> {
    trace_operation("analysis.extract_cohort", Some("extract_cohort"), || {
        cohort.validate()?;
        let database = connect_database(paths, resources)?;
        load_item_assets(&database, paths)?;
        extract_source_players(&database, paths, cohort, resources)?;
        eprintln!("Preparing match tables");
        database.execute(
            sql!("extract/create_eligible_matches"),
            &Parameters::from([(
                "as_of".into(),
                SqlValue::Timestamp(TimeUnit::Second, cohort.as_of),
            )]),
        )?;
        database.execute(sql!("extract/create_player_matches"), &Parameters::new())?;
        create_match_folds(&database, cohort)?;
        for query in [
            sql!("extract/create_player_snapshots"),
            sql!("extract/create_team_snapshots"),
            sql!("extract/create_purchases"),
        ] {
            database.execute(query, &Parameters::new())?;
        }
        let counts = collect_extraction_counts(&database)?;
        drop(database);
        let temporary = paths.raw.join("duckdb-tmp");
        if temporary.is_dir() {
            std::fs::remove_dir_all(temporary)?;
        }
        Ok(counts)
    })
}

fn connect_database(paths: &RunPaths, resources: ExtractionResources) -> Result<AnalysisDatabase> {
    let database = AnalysisDatabase::open(&paths.database(), resources)?;
    database.execute(
        sql!("extract/set_temp_directory"),
        &Parameters::from([(
            "directory".into(),
            paths
                .raw
                .join("duckdb-tmp")
                .to_string_lossy()
                .into_owned()
                .into(),
        )]),
    )?;
    database.execute(sql!("extract/load_extensions"), &Parameters::new())?;
    database.execute(sql!("extract/create_s3_secret"), &Parameters::new())?;
    database.execute(
        sql!("extract/create_ducklake_secret"),
        &Parameters::from([("metadata_path".into(), SqlValue::Text(DUCKLAKE_URL.into()))]),
    )?;
    database.execute(sql!("extract/attach_remote"), &Parameters::new())?;
    let version = database.count(sql!("extract/select_current_snapshot"), &Parameters::new())?;
    database.execute(sql!("extract/detach_remote"), &Parameters::new())?;
    let version = Parameters::from([("version".into(), SqlValue::UBigInt(version))]);
    database.execute(sql!("extract/attach_remote_snapshot"), &version)?;
    database.execute(sql!("extract/create_source_snapshot"), &version)?;
    Ok(database)
}

/// Copies the cohort rows from the remote lake once, keeping the newest
/// version of each player row. Later extraction steps read only this table.
///
/// The cache keeps the rows of each remote file, so a run downloads only new files.
/// Remote reads wait on HTTP requests, so this step uses more threads than local steps.
fn extract_source_players(
    database: &AnalysisDatabase,
    paths: &RunPaths,
    cohort: &Cohort,
    resources: ExtractionResources,
) -> Result<()> {
    eprintln!(
        "Downloading ranked matches from {} to {}",
        format_timestamp(cohort.since)?,
        format_timestamp(cohort.as_of)?
    );
    set_threads(database, resources.threads.max(REMOTE_READ_THREADS))?;
    attach_cache(database, &paths.cache, cohort)?;
    let version = database.count(sql!("extract/select_source_snapshot"), &Parameters::new())?;
    database.execute(
        sql!("extract/create_remote_files"),
        &Parameters::from([("version".into(), SqlValue::UBigInt(version))]),
    )?;
    database.execute(sql!("extract/delete_stale_cache_rows"), &Parameters::new())?;
    let missing = database
        .query_rows::<RemoteFile>(sql!("extract/select_missing_files"), &Parameters::new())?;
    let files = database.count(
        sql!("extract/count_table_rows"),
        &Parameters::from([("table".into(), SqlValue::Text("remote_files".into()))]),
    )?;
    eprintln!(
        "Remote files: {} new, {} from the cache",
        missing.len(),
        files.saturating_sub(u64::try_from(missing.len())?)
    );
    let parameters = build_cohort_parameters(cohort);
    download_files(database, &missing, &parameters)?;
    database.execute_remote(sql!("extract/create_catalog_players"), &parameters)?;
    database.execute(
        sql!("extract/create_source_players"),
        &Parameters::from([(
            "as_of".into(),
            SqlValue::Timestamp(TimeUnit::Second, cohort.as_of),
        )]),
    )?;
    set_threads(database, resources.threads)
}

/// Attaches the cache of remote rows and removes the caches of other cohorts.
///
/// The file name contains a fingerprint of the cohort filters and of the cache SQL,
/// so a change of either one starts a new cache.
fn attach_cache(database: &AnalysisDatabase, directory: &Path, cohort: &Cohort) -> Result<()> {
    let key = fingerprint(&json!({
        "filters": cohort.cache_filters()?,
        "sql": [sql!("extract/create_cache_tables"), sql!("extract/insert_cache_players")],
    }))?;
    let name = format!("remote-players-{key}.duckdb");
    std::fs::create_dir_all(directory)?;
    for entry in std::fs::read_dir(directory)? {
        let entry = entry?;
        if !entry.file_name().to_string_lossy().starts_with(&name) {
            std::fs::remove_file(entry.path())?;
        }
    }
    database.execute(
        sql!("extract/attach_cache"),
        &Parameters::from([(
            "path".into(),
            SqlValue::Text(directory.join(name).to_string_lossy().into_owned()),
        )]),
    )?;
    database.execute(sql!("extract/create_cache_tables"), &Parameters::new())
}

/// Downloads the cohort rows of the files into the cache, on several connections at a time.
fn download_files(
    database: &AnalysisDatabase,
    files: &[RemoteFile],
    parameters: &Parameters,
) -> Result<()> {
    let connections = (0..REMOTE_DOWNLOAD_CONNECTIONS.min(files.len()))
        .map(|_| database.try_clone())
        .collect::<Result<Vec<_>>>()?;
    let next = AtomicUsize::new(0);
    std::thread::scope(|scope| {
        let downloads = connections
            .into_iter()
            .map(|connection| {
                let next = &next;
                scope.spawn(move || download_next_files(&connection, files, parameters, next))
            })
            .collect::<Vec<_>>();
        for download in downloads {
            download
                .join()
                .map_err(|_| Error::new("A remote download thread stopped unexpectedly"))??;
        }
        Ok(())
    })
}

/// Downloads files until none remain. A failure stops the other threads at their next file.
///
/// The file row follows the rows of the file, so an interrupted copy does not count.
fn download_next_files(
    connection: &AnalysisDatabase,
    files: &[RemoteFile],
    parameters: &Parameters,
    next: &AtomicUsize,
) -> Result<()> {
    let mut parameters = parameters.clone();
    while let Some(file) = files.get(next.fetch_add(1, Ordering::Relaxed)) {
        let name = Parameters::from([("data_file".into(), SqlValue::Text(file.data_file.clone()))]);
        parameters.extend(name.clone());
        let result = connection
            .execute_remote(sql!("extract/insert_cache_players"), &parameters)
            .and_then(|()| connection.execute(sql!("extract/insert_cache_file"), &name));
        if let Err(error) = result {
            next.store(files.len(), Ordering::Relaxed);
            return Err(error);
        }
    }
    Ok(())
}

fn set_threads(database: &AnalysisDatabase, threads: u16) -> Result<()> {
    database.execute(
        sql!("extract/set_threads"),
        &Parameters::from([("threads".into(), i64::from(threads).into())]),
    )
}

fn build_cohort_parameters(cohort: &Cohort) -> Parameters {
    Parameters::from([
        ("match_mode".into(), SqlValue::Text("Ranked".into())),
        ("game_mode".into(), SqlValue::Text("Normal".into())),
        (
            "since".into(),
            SqlValue::Timestamp(TimeUnit::Second, cohort.since),
        ),
        (
            "minimum_badge".into(),
            i64::from(cohort.ranks.minimum.badge()).into(),
        ),
        (
            "maximum_badge".into(),
            i64::from(cohort.ranks.maximum.badge()).into(),
        ),
    ])
}

fn load_item_assets(database: &AnalysisDatabase, paths: &RunPaths) -> Result<()> {
    let document = read_json(&paths.raw.join("items.json"))?;
    let rows = array(&document)?
        .iter()
        .map(build_item_asset_row)
        .collect::<Result<Vec<_>>>()?;
    database.execute(sql!("extract/create_item_assets"), &Parameters::new())?;
    database.insert_rows(sql!("extract/insert_item_assets"), &rows)
}

fn build_item_asset_row(item: &Value) -> Result<Vec<SqlValue>> {
    let identifier = integer(item, "id")?;
    Ok(vec![
        SqlValue::UBigInt(identifier),
        item["name"]
            .as_str()
            .map_or_else(|| format!("Item {identifier}"), str::to_owned)
            .into(),
        SqlValue::Text(item["class_name"].as_str().unwrap_or_default().into()),
        SqlValue::UBigInt(integer(item, "item_tier")?),
        SqlValue::UBigInt(item["cost"].as_u64().unwrap_or(0)),
        item["item_slot_type"]
            .as_str()
            .unwrap_or("unknown")
            .to_lowercase()
            .into(),
        serde_json::to_string(
            item.get("component_items")
                .filter(|value| value.is_array())
                .unwrap_or(&json!([])),
        )?
        .into(),
    ])
}

fn create_match_folds(database: &AnalysisDatabase, cohort: &Cohort) -> Result<()> {
    database.execute(
        sql!("extract/create_split_boundaries"),
        &Parameters::from([
            (
                "minimum_badge".into(),
                i64::from(cohort.ranks.minimum.badge()).into(),
            ),
            (
                "maximum_badge".into(),
                i64::from(cohort.ranks.maximum.badge()).into(),
            ),
        ]),
    )?;
    let start = deadlock_data::count_as_f64(u64::try_from(cohort.since)?)?;
    let end = deadlock_data::count_as_f64(u64::try_from(cohort.as_of)?)?;
    let parameters = [
        ("discovery_end", 0.45),
        ("train_end", 0.6),
        ("validation_end", 0.8),
    ]
    .into_iter()
    .map(|(name, share)| {
        (
            name.into(),
            SqlValue::Double((end - start).mul_add(share, start)),
        )
    })
    .collect();
    database.execute(sql!("extract/fill_split_boundaries"), &parameters)?;
    database.execute(sql!("extract/create_match_folds"), &Parameters::new())
}

fn collect_extraction_counts(database: &AnalysisDatabase) -> Result<ExtractionRecord> {
    let count_rows = |table: &str| {
        database.count(
            sql!("extract/count_table_rows"),
            &Parameters::from([("table".into(), SqlValue::Text(table.into()))]),
        )
    };
    Ok(ExtractionRecord {
        player_matches: count_rows("player_matches")?,
        match_folds: count_rows("match_folds")?,
        purchases: count_rows("purchases")?,
        heroes: database.count(sql!("extract/count_heroes"), &Parameters::new())?,
        source_snapshot_version: database
            .count(sql!("extract/select_source_snapshot"), &Parameters::new())?,
    })
}
