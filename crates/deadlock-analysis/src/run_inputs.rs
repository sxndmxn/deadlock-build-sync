use duckdb::types::Value as SqlValue;
use serde::Deserialize;

use std::collections::BTreeSet;

use deadlock_data::{Error, RankRange, Result};

use crate::build_assembly::{PurchaseMedian, PurchaseMedians};
use crate::build_evaluation::EVALUATION_LANDMARKS;
use crate::database::{AnalysisDatabase, Parameters};
use crate::item_effects::{ItemCatalog, LandmarkState};
use crate::refresh_configuration::{ExtractionResources, RunPaths};
use crate::run_manifest::RunManifest;
use crate::sql_resources::sql;

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
#[derive(Debug)]
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
        &paths.database(),
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
    let states: Vec<LandmarkState> =
        database.query_rows(sql!("builds/select_landmark_states"), parameters)?;
    // The SQL landmark list must cover the evaluation landmarks, which cover the phases.
    let landmarks = states
        .iter()
        .map(|state| state.landmark_s)
        .collect::<BTreeSet<_>>();
    if let Some(missing) = EVALUATION_LANDMARKS
        .iter()
        .find(|landmark| !landmarks.contains(landmark))
    {
        return Err(Error::new(format!(
            "The extracted landmark states have no rows at {missing} s. The run has too few matches, or select_landmark_states.sql dropped a landmark"
        )));
    }
    let catalog = ItemCatalog::new(
        database.query_rows(sql!("builds/select_item_assets"), &Parameters::new())?,
    )?;
    let medians = database
        .query_rows::<PurchaseMedianRow>(sql!("builds/select_item_purchase_medians"), parameters)?
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
    let ranks = RunManifest::read(paths)?.cohort.ranks()?;
    let (database, parameters) = open_run_database(paths, resources, ranks)?;
    load_assembly_inputs(&database, &parameters)
}
