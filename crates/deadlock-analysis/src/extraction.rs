use deadlock_data::{Result, array, integer, read_json, trace_operation};
use duckdb::types::{TimeUnit, Value as SqlValue};
use serde_json::{Value, json};

use crate::database::{AnalysisDatabase, Parameters};
use crate::refresh_configuration::{Cohort, DUCKLAKE_URL, ExtractionResources, RunPaths};
use crate::sql_resources::sql;

/// 64 threads read one day of remote rows 3.8 times faster than 8 threads, at equal bytes.
const REMOTE_READ_THREADS: u16 = 64;

pub fn extract_cohort(
    paths: &RunPaths,
    cohort: &Cohort,
    resources: ExtractionResources,
) -> Result<Value> {
    trace_operation("analysis.extract_cohort", Some("extract_cohort"), || {
        cohort.validate()?;
        let database = connect_database(paths, resources)?;
        load_item_assets(&database, paths)?;
        extract_source_players(&database, cohort, resources)?;
        database.execute(
            sql!("extract/create_eligible_matches"),
            &Parameters::from([(
                "as_of".into(),
                SqlValue::Timestamp(TimeUnit::Second, cohort.as_of),
            )]),
        )?;
        extract_table(
            &database,
            "player_matches",
            sql!("extract/create_player_matches"),
        )?;
        create_match_folds(&database, cohort)?;
        for (table, query) in [
            ("player_snapshots", sql!("extract/create_player_snapshots")),
            ("team_snapshots", sql!("extract/create_team_snapshots")),
            ("purchases", sql!("extract/create_purchases")),
        ] {
            extract_table(&database, table, query)?;
        }
        let counts = collect_extraction_counts(&database, cohort)?;
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
/// Remote reads wait on HTTP requests, so this step uses more threads than local steps.
fn extract_source_players(
    database: &AnalysisDatabase,
    cohort: &Cohort,
    resources: ExtractionResources,
) -> Result<()> {
    eprintln!("Extracting source_players");
    set_threads(database, resources.threads.max(REMOTE_READ_THREADS))?;
    database.execute_remote(
        sql!("extract/create_source_players"),
        &build_cohort_parameters(cohort),
    )?;
    set_threads(database, resources.threads)
}

fn set_threads(database: &AnalysisDatabase, threads: u16) -> Result<()> {
    database.execute(
        sql!("extract/set_threads"),
        &Parameters::from([("threads".into(), i64::from(threads).into())]),
    )
}

fn extract_table(database: &AnalysisDatabase, table: &str, query: &str) -> Result<()> {
    eprintln!("Extracting {table}");
    database.execute(query, &Parameters::new())
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

fn collect_extraction_counts(database: &AnalysisDatabase, cohort: &Cohort) -> Result<Value> {
    let mut counts = serde_json::Map::new();
    for table in ["player_matches", "match_folds", "purchases"] {
        let count = database.count(
            sql!("extract/count_table_rows"),
            &Parameters::from([("table".into(), SqlValue::Text(table.into()))]),
        )?;
        counts.insert(table.into(), count.into());
    }
    for (name, query) in [
        (
            "source_snapshot_version",
            sql!("extract/select_source_snapshot"),
        ),
        ("heroes", sql!("extract/count_heroes")),
    ] {
        counts.insert(
            name.into(),
            database.count(query, &Parameters::new())?.into(),
        );
    }
    counts.insert(
        "extracted_minimum_badge".into(),
        cohort.ranks.minimum.badge().into(),
    );
    Ok(counts.into())
}
