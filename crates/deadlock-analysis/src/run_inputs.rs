use duckdb::types::Value as SqlValue;
use serde::Deserialize;

use deadlock_data::{RankRange, Result, read_json};

use crate::build_assembly::{PurchaseMedian, PurchaseMedians};
use crate::database::{AnalysisDatabase, Parameters};
use crate::item_effects::{ItemCatalog, LandmarkState};
use crate::refresh_configuration::{ExtractionResources, RunPaths, cohort_ranks};
use crate::sql_resources::load_sql;

#[derive(Debug, Deserialize)]
struct PurchaseMedianRow {
    hero_id: u64,
    item_id: u64,
    median_buy_time_s: f64,
    median_net_worth: u32,
    lower_quartile_net_worth: u32,
    upper_quartile_net_worth: u32,
}

/// Landmark states, shop items, and purchase medians for build assembly.
pub struct AssemblyInputs {
    pub states: Vec<LandmarkState>,
    pub catalog: ItemCatalog,
    pub medians: PurchaseMedians,
}

/// Opens the run database with the rank parameters of the run cohort.
pub fn open_run_database(
    paths: &RunPaths,
    resources: ExtractionResources,
    ranks: RankRange,
) -> Result<(AnalysisDatabase, Parameters)> {
    let database = AnalysisDatabase::open_read_only(
        &paths.raw.join("analysis.duckdb"),
        &paths.raw.join("duckdb-read-tmp"),
        resources,
    )?;
    let parameters = Parameters::from([
        (
            "minimum_badge".into(),
            SqlValue::UInt(u32::from(ranks.minimum.badge())),
        ),
        (
            "maximum_badge".into(),
            SqlValue::UInt(u32::from(ranks.maximum.badge())),
        ),
    ]);
    Ok((database, parameters))
}

pub fn load_assembly_inputs(
    database: &AnalysisDatabase,
    parameters: &Parameters,
) -> Result<AssemblyInputs> {
    eprintln!("Loading landmark states");
    let states = database.query_rows(load_sql("builds/select_landmark_states.sql")?, parameters)?;
    let catalog = ItemCatalog::new(database.query_rows(
        load_sql("builds/select_item_assets.sql")?,
        &Parameters::new(),
    )?)?;
    let medians = database
        .query_rows::<PurchaseMedianRow>(
            load_sql("builds/select_item_purchase_medians.sql")?,
            parameters,
        )?
        .into_iter()
        .map(|row| {
            (
                (row.hero_id, row.item_id),
                PurchaseMedian {
                    buy_time_s: row.median_buy_time_s,
                    net_worth: row.median_net_worth,
                    soul_window: [row.lower_quartile_net_worth, row.upper_quartile_net_worth],
                },
            )
        })
        .collect();
    Ok(AssemblyInputs {
        states,
        catalog,
        medians,
    })
}

/// Loads the assembly inputs of a run with the rank range of its manifest.
///
/// # Errors
/// Returns an error when the manifest, the analysis database, or a query fails.
pub fn load_run_inputs(paths: &RunPaths, resources: ExtractionResources) -> Result<AssemblyInputs> {
    let manifest = read_json(&paths.run.join("manifest.json"))?;
    let ranks = cohort_ranks(&manifest["cohort"])?;
    let (database, parameters) = open_run_database(paths, resources, ranks)?;
    load_assembly_inputs(&database, &parameters)
}
