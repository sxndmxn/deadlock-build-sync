use deadlock_data::{Result, array, integer, read_json, trace_operation};
use duckdb::types::{TimeUnit, Value as SqlValue};
use serde_json::{Value, json};

use crate::database::{AnalysisDatabase, Parameters};
use crate::refresh_configuration::{Cohort, DUCKLAKE_URL, ExtractionResources, RunPaths};
use crate::sql_resources::load_sql;

/// 64 threads read one day of remote rows 3.8 times faster than 8 threads, at equal bytes.
const REMOTE_READ_THREADS: u16 = 64;

pub fn extract_cohort(
    paths: &RunPaths,
    cohort: &Cohort,
    resources: ExtractionResources,
) -> Result<Value> {
    trace_operation("analysis.extract_cohort", Some("extract_cohort"), || {
        cohort.validate()?;
        let extraction = cohort.clone();
        let database = connect_database(paths, resources)?;
        load_item_assets(&database, paths)?;
        extract_source_players(&database, &extraction, resources)?;
        execute_sql_resource(&database, "drop_eligible_matches", &Parameters::new())?;
        execute_sql_resource(
            &database,
            "create_eligible_matches",
            &Parameters::from([(
                "as_of".into(),
                SqlValue::Timestamp(TimeUnit::Second, extraction.as_of),
            )]),
        )?;
        extract_table(&database, "player_matches")?;
        create_match_folds(&database, cohort)?;
        for table in ["player_snapshots", "team_snapshots", "purchases"] {
            extract_table(&database, table)?;
        }
        let counts = collect_extraction_counts(&database, &extraction)?;
        drop(database);
        let temporary = paths.raw.join("duckdb-tmp");
        if temporary.is_dir() {
            std::fs::remove_dir_all(temporary)?;
        }
        Ok(counts)
    })
}

fn connect_database(paths: &RunPaths, resources: ExtractionResources) -> Result<AnalysisDatabase> {
    let database = AnalysisDatabase::open(&paths.raw.join("analysis.duckdb"), resources)?;
    execute_sql_resource(
        &database,
        "set_temp_directory",
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
    for command in ["load_extensions", "create_s3_secret"] {
        execute_sql_resource(&database, command, &Parameters::new())?;
    }
    execute_sql_resource(
        &database,
        "create_ducklake_secret",
        &Parameters::from([("metadata_path".into(), SqlValue::Text(DUCKLAKE_URL.into()))]),
    )?;
    execute_sql_resource(&database, "attach_remote", &Parameters::new())?;
    let version = database.count(
        load_sql("extract/select_current_snapshot.sql")?,
        &Parameters::new(),
    )?;
    execute_sql_resource(&database, "detach_remote", &Parameters::new())?;
    let version = Parameters::from([("version".into(), SqlValue::UBigInt(version))]);
    execute_sql_resource(&database, "attach_remote_snapshot", &version)?;
    execute_sql_resource(&database, "create_source_snapshot", &version)?;
    Ok(database)
}

fn execute_sql_resource(
    database: &AnalysisDatabase,
    name: &str,
    parameters: &Parameters,
) -> Result<()> {
    database.execute(load_sql(&format!("extract/{name}.sql"))?, parameters)
}

/// Copies the cohort rows from the remote lake once, keeping the newest
/// version of each player row. Later extraction steps read only this table.
///
/// Remote reads wait on HTTP requests, so this step uses more threads than local steps.
fn extract_source_players(
    database: &AnalysisDatabase,
    cohort: &Cohort,
    resources: ExtractionResources,
) -> Result<()> {
    eprintln!("Extracting source_players");
    execute_sql_resource(database, "drop_source_players", &Parameters::new())?;
    set_threads(database, resources.threads.max(REMOTE_READ_THREADS))?;
    database.execute_remote(
        load_sql("extract/create_source_players.sql")?,
        &build_cohort_parameters(cohort),
    )?;
    set_threads(database, resources.threads)
}

fn set_threads(database: &AnalysisDatabase, threads: u16) -> Result<()> {
    execute_sql_resource(
        database,
        "set_threads",
        &Parameters::from([("threads".into(), i64::from(threads).into())]),
    )
}

fn extract_table(database: &AnalysisDatabase, table: &str) -> Result<()> {
    eprintln!("Extracting {table}");
    execute_sql_resource(database, &format!("drop_{table}"), &Parameters::new())?;
    execute_sql_resource(database, &format!("create_{table}"), &Parameters::new())
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
            "as_of".into(),
            SqlValue::Timestamp(TimeUnit::Second, cohort.as_of),
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
    for name in ["drop_item_assets", "create_item_assets"] {
        execute_sql_resource(database, name, &Parameters::new())?;
    }
    database.insert_rows(load_sql("extract/insert_item_assets.sql")?, &rows)
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
        item["is_active_item"].as_bool().unwrap_or(false).into(),
        item["is_unique"].as_bool().unwrap_or(true).into(),
        serde_json::to_string(
            item.get("component_items")
                .filter(|value| value.is_array())
                .unwrap_or(&json!([])),
        )?
        .into(),
    ])
}

fn create_match_folds(database: &AnalysisDatabase, cohort: &Cohort) -> Result<()> {
    execute_sql_resource(
        database,
        "create_split_boundaries",
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
    execute_sql_resource(database, "fill_split_boundaries", &parameters)?;
    execute_sql_resource(database, "create_match_folds", &Parameters::new())
}

fn collect_extraction_counts(database: &AnalysisDatabase, cohort: &Cohort) -> Result<Value> {
    let mut counts = serde_json::Map::new();
    for table in ["player_matches", "match_folds", "purchases"] {
        let count = database.count(
            load_sql("extract/count_table_rows.sql")?,
            &Parameters::from([("table".into(), SqlValue::Text(table.into()))]),
        )?;
        counts.insert(table.into(), count.into());
    }
    for (name, query) in [
        ("source_snapshot_version", "select_source_snapshot"),
        ("heroes", "count_heroes"),
    ] {
        counts.insert(
            name.into(),
            database
                .count(
                    load_sql(&format!("extract/{query}.sql"))?,
                    &Parameters::new(),
                )?
                .into(),
        );
    }
    counts.insert(
        "extracted_minimum_badge".into(),
        cohort.ranks.minimum.badge().into(),
    );
    Ok(counts.into())
}
