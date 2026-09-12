use std::collections::BTreeMap;

use deadlock_data::{RankRange, Result, count_as_f64, count_ratio, integer};

use crate::database::{AnalysisDatabase, Parameters};
use crate::discovery_data::DiscoveryData;
use crate::sql_resources::load_sql;

#[derive(Debug)]
pub struct BeamModel {
    cells: BTreeMap<(u64, u8, u64), (u64, u64)>,
    baselines: BTreeMap<(u64, u8), f64>,
    prior: f64,
}

impl BeamModel {
    pub fn load(
        database: &AnalysisDatabase,
        data: &DiscoveryData,
        ranks: RankRange,
    ) -> Result<Self> {
        let parameters = Parameters::from([
            ("hero".into(), duckdb::types::Value::UBigInt(data.hero)),
            (
                "minimum_badge".into(),
                i64::from(ranks.minimum.badge()).into(),
            ),
            (
                "maximum_badge".into(),
                i64::from(ranks.maximum.badge()).into(),
            ),
        ]);
        let mut cells = BTreeMap::new();
        let mut totals = BTreeMap::<(u64, u8), (u64, u64)>::new();
        for row in database.query(load_sql("beam/select_item_counts.sql")?, &parameters)? {
            let (wealth, state, item) = (
                integer(&row, "wealth_bin")?,
                u8::try_from(integer(&row, "relative_state")?)?,
                integer(&row, "item_id")?,
            );
            let (count, wins) = (integer(&row, "purchases")?, integer(&row, "wins")?);
            cells.insert((wealth, state, item), (count, wins));
            let total = totals.entry((wealth, state)).or_default();
            total.0 += count;
            total.1 += wins;
        }
        let discovery = data.fold_rows("discovery").collect::<Vec<_>>();
        let wins = discovery
            .iter()
            .filter(|index| data.rows[**index].won)
            .count();
        let prior = count_ratio(
            u64::try_from(wins)? + 1,
            u64::try_from(discovery.len())? + 2,
        )?;
        let baselines = totals
            .into_iter()
            .map(|(key, (count, wins))| {
                Ok((
                    key,
                    20.0f64.mul_add(prior, count_as_f64(wins)?) / (count_as_f64(count)? + 20.0),
                ))
            })
            .collect::<Result<_>>()?;
        Ok(Self {
            cells,
            baselines,
            prior,
        })
    }

    pub fn score(
        &self,
        wealth: u64,
        state: u8,
        item: u64,
        cost: u64,
        depth: usize,
    ) -> Result<Option<f64>> {
        let key = ((wealth / 4000).min(11), state, item);
        let (count, wins) = self.cells.get(&key).copied().unwrap_or_default();
        if count < 30 {
            return Ok(None);
        }
        let baseline = self
            .baselines
            .get(&(key.0, key.1))
            .copied()
            .unwrap_or(self.prior);
        let total = count_as_f64(count)? + 1000.0;
        let alpha = 1000.0f64.mul_add(baseline, count_as_f64(wins)?);
        let beta = total - alpha;
        let variance = alpha * beta / (total.powi(2) * (total + 1.0));
        let utility = 0.5f64.mul_add(-variance.sqrt(), alpha / total - baseline);
        let scale = count_as_f64(cost.max(800))? / 1600.0;
        Ok(Some(
            utility * 0.97_f64.powi(i32::try_from(depth)?) / scale.sqrt(),
        ))
    }
}
