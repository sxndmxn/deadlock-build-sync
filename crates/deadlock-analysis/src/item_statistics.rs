use std::collections::BTreeMap;

use deadlock_data::{Error, Result};
use deadlock_guides::{HeroBuild, ItemStatistics};
use serde::Deserialize;

use crate::database::{AnalysisDatabase, Parameters};
use crate::sql_resources::load_sql;

#[derive(Debug, Deserialize)]
struct ItemStatisticsRow {
    hero_id: u64,
    item_id: u64,
    hero_matches: u64,
    buyer_matches: u64,
    buyer_wins: u64,
}

pub type HeroItemStatistics = BTreeMap<(u64, u64), ItemStatistics>;

pub fn load_item_statistics(
    database: &AnalysisDatabase,
    parameters: &Parameters,
) -> Result<HeroItemStatistics> {
    database
        .query_rows::<ItemStatisticsRow>(
            load_sql("builds/select_item_statistics.sql")?,
            parameters,
        )?
        .into_iter()
        .map(|row| {
            let statistics = ItemStatistics {
                hero_matches: row.hero_matches,
                buyer_matches: row.buyer_matches,
                buyer_wins: row.buyer_wins,
            };
            statistics.validate()?;
            Ok(((row.hero_id, row.item_id), statistics))
        })
        .collect()
}

pub fn attach_item_statistics(
    build: &mut HeroBuild,
    statistics: &HeroItemStatistics,
) -> Result<()> {
    for item in build.core.iter_mut().chain(&mut build.situational) {
        item.statistics = Some(
            statistics
                .get(&(build.hero_id, item.item_id))
                .ok_or_else(|| {
                    Error::new(format!(
                        "Purchase statistics are missing for hero {} and item {}",
                        build.hero_id, item.item_id
                    ))
                })?
                .clone(),
        );
    }
    Ok(())
}
