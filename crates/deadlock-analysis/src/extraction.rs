use deadlock_data::{Result, array, integer, read_json, trace_operation};
use deadlock_guides::{RankExpansion, calculate_rank_cutoffs};
use duckdb::types::{TimeUnit, Value as SqlValue};
use serde_json::{Value, json};

use crate::config::{Cohort, DUCKLAKE_URL, RunPaths};
use crate::database::{AnalysisDatabase, Parameters};
use crate::sql_resources::load_sql;

const TABLES: [&str; 12] = [
    "item_assets",
    "eligible_matches",
    "player_matches",
    "hero_account_counts",
    "match_folds",
    "split_boundaries",
    "compositions",
    "team_snapshots",
    "player_snapshots",
    "purchases",
    "first_purchases",
    "decision_opportunities",
];

pub fn extract_cohort(
    paths: &RunPaths,
    cohort: &Cohort,
    expansion: RankExpansion,
) -> Result<Value> {
    trace_operation("analysis.extract_cohort", Some("extract_cohort"), || {
        cohort.validate()?;
        let cutoffs =
            calculate_rank_cutoffs(cohort.ranks.minimum, cohort.ranks.maximum, expansion)?;
        let mut extraction = cohort.clone();
        if let Some(minimum) = cutoffs.last() {
            extraction.ranks.minimum = *minimum;
        }
        let database = connect_database(paths)?;
        load_item_assets(&database, paths)?;
        execute(&database, "drop_eligible_matches", &Parameters::new())?;
        database.execute_remote(
            load_sql("extract/create_eligible_matches.sql")?,
            &cohort_parameters(&extraction),
        )?;
        for table in ["player_matches", "hero_account_counts"] {
            extract_remote_table(&database, table)?;
        }
        freeze_splits(&database, cohort)?;
        execute(&database, "create_compositions", &Parameters::new())?;
        for table in ["player_snapshots", "team_snapshots", "purchases"] {
            extract_remote_table(&database, table)?;
        }
        for table in ["first_purchases", "decision_opportunities"] {
            execute(&database, &format!("drop_{table}"), &Parameters::new())?;
            execute(&database, &format!("create_{table}"), &Parameters::new())?;
        }
        export_tables(&database, paths)?;
        let counts = extraction_counts(&database, &extraction)?;
        drop(database);
        let temporary = paths.raw.join("duckdb-tmp");
        if temporary.is_dir() {
            std::fs::remove_dir_all(temporary)?;
        }
        Ok(counts)
    })
}

fn connect_database(paths: &RunPaths) -> Result<AnalysisDatabase> {
    let database = AnalysisDatabase::open(&paths.raw.join("analysis.duckdb"))?;
    for command in ["set_threads", "set_memory_limit"] {
        execute(&database, command, &Parameters::new())?;
    }
    execute(
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
        execute(&database, command, &Parameters::new())?;
    }
    execute(
        &database,
        "create_ducklake_secret",
        &Parameters::from([("metadata_path".into(), SqlValue::Text(DUCKLAKE_URL.into()))]),
    )?;
    execute(&database, "attach_remote", &Parameters::new())?;
    let version = database.count(
        load_sql("extract/select_current_snapshot.sql")?,
        &Parameters::new(),
    )?;
    execute(&database, "detach_remote", &Parameters::new())?;
    let version = Parameters::from([("version".into(), SqlValue::UBigInt(version))]);
    execute(&database, "attach_remote_snapshot", &version)?;
    execute(&database, "create_source_snapshot", &version)?;
    Ok(database)
}

fn execute(database: &AnalysisDatabase, name: &str, parameters: &Parameters) -> Result<()> {
    database.execute(load_sql(&format!("extract/{name}.sql"))?, parameters)
}

fn extract_remote_table(database: &AnalysisDatabase, table: &str) -> Result<()> {
    eprintln!("Extracting {table}");
    execute(database, &format!("drop_{table}"), &Parameters::new())?;
    database.execute_remote(
        load_sql(&format!("extract/create_{table}.sql"))?,
        &Parameters::new(),
    )
}

fn cohort_parameters(cohort: &Cohort) -> Parameters {
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
        .map(item_row)
        .collect::<Result<Vec<_>>>()?;
    for name in ["drop_item_assets", "create_item_assets"] {
        execute(database, name, &Parameters::new())?;
    }
    database.insert_rows(load_sql("extract/insert_item_assets.sql")?, &rows)
}

fn item_row(item: &Value) -> Result<Vec<SqlValue>> {
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

fn freeze_splits(database: &AnalysisDatabase, cohort: &Cohort) -> Result<()> {
    execute(
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
    execute(database, "fill_split_boundaries", &parameters)?;
    execute(database, "create_match_folds", &Parameters::new())
}

fn export_tables(database: &AnalysisDatabase, paths: &RunPaths) -> Result<()> {
    for table in TABLES {
        execute(
            database,
            "export_table",
            &Parameters::from([
                ("table".into(), SqlValue::Text(table.into())),
                (
                    "path".into(),
                    paths
                        .data
                        .join(format!("{table}.parquet"))
                        .to_string_lossy()
                        .into_owned()
                        .into(),
                ),
            ]),
        )?;
    }
    Ok(())
}

fn extraction_counts(database: &AnalysisDatabase, cohort: &Cohort) -> Result<Value> {
    let mut counts = serde_json::Map::new();
    for table in [
        "player_matches",
        "match_folds",
        "purchases",
        "first_purchases",
        "decision_opportunities",
    ] {
        let count = database.count(
            load_sql("extract/count_table_rows.sql")?,
            &Parameters::from([("table".into(), SqlValue::Text(table.into()))]),
        )?;
        counts.insert(table.into(), count.into());
    }
    for (name, query) in [
        ("source_snapshot_version", "select_source_snapshot"),
        ("heroes", "count_heroes"),
        ("hero_account_rows", "count_hero_accounts"),
        ("valid_purchase_net_worth", "count_purchase_net_worth"),
        ("valid_team_lead", "count_team_lead"),
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
