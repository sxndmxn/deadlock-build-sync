use std::collections::BTreeMap;

use deadlock_data::{RankRange, Result, array, integer, read_json};
use deadlock_guides::RankExpansion;
use deadlock_input::ItemGraph;
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::config::RunPaths;
use crate::database::AnalysisDatabase;
use crate::discovery_data::prepare_partitions;
use crate::mining::Candidate;
use crate::purchase_pool::FrozenGuide;

#[derive(Debug)]
pub struct ExportContext {
    pub paths: RunPaths,
    pub normal_assets: Vec<Value>,
    pub graph: ItemGraph,
    pub assets: BTreeMap<u64, Value>,
    pub ranks: RankRange,
    pub expansion: RankExpansion,
}

impl ExportContext {
    pub fn load(paths: &RunPaths, manifest: &Value) -> Result<Self> {
        let all = read_json(&paths.raw.join("items-all.json"))?;
        let normal_assets = array(&all)?
            .iter()
            .filter(|item| {
                item["game_mode"]
                    .as_str()
                    .unwrap_or("normal")
                    .eq_ignore_ascii_case("normal")
            })
            .cloned()
            .collect::<Vec<_>>();
        let shop = read_json(&paths.raw.join("items.json"))?;
        Ok(Self {
            paths: paths.clone(),
            graph: ItemGraph::from_assets(array(&shop)?)?,
            assets: normal_assets
                .iter()
                .map(|item| Ok((integer(item, "id")?, item.clone())))
                .collect::<Result<_>>()?,
            normal_assets,
            ranks: crate::config::cohort_ranks(&manifest["cohort"])?,
            expansion: serde_json::from_value(manifest["rank_expansion"].clone())?,
        })
    }

    pub fn open_database(&self, hero: u64) -> Result<AnalysisDatabase> {
        let database = AnalysisDatabase::open_read_only(
            &self.paths.raw.join("analysis.duckdb"),
            &self.paths.run.join("duckdb-workers").join(hero.to_string()),
        )?;
        prepare_partitions(&database)?;
        Ok(database)
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Nomination {
    #[serde(flatten)]
    pub candidate: Candidate,
    pub hero_id: u64,
    pub selection_rank: usize,
    pub path: Value,
    pub guide: FrozenGuide,
    pub tactics: Value,
    pub branch_candidates: Vec<Value>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct FrozenHero {
    pub cohort: Value,
    pub rows: Vec<Nomination>,
    pub candidate_count: usize,
    pub grouping: Value,
    pub candidates: Vec<Candidate>,
}

pub fn item_ids(value: &Value) -> Result<Vec<u64>> {
    Ok(serde_json::from_value(value.clone())?)
}
