use std::collections::BTreeSet;

use deadlock_data::{Error, Result, integer};
use ndarray::{Array2, Axis};
use serde_json::Value;

use crate::contrast_context::{ContextColumns, numeric_feature};

const STATE_FEATURES: [&str; 11] = [
    "average_badge",
    "phase",
    "buy_time",
    "own_net_worth_at_buy",
    "state_observed_at_s",
    "own_team_net_worth",
    "enemy_team_net_worth",
    "team_net_worth_lead",
    "state_age_s",
    "prior_catalog_spend",
    "prior_purchase_count",
];

#[derive(Clone, Debug)]
pub struct Observations {
    pub features: Array2<f64>,
    pub treatment: Vec<f64>,
    pub outcome: Vec<f64>,
    pub matches: Vec<u64>,
    pub periods: Vec<String>,
}

impl Observations {
    pub fn from_rows<'a>(
        rows: impl IntoIterator<Item = &'a Value>,
        treatment: u64,
    ) -> Result<Self> {
        let rows = rows.into_iter().collect::<Vec<_>>();
        let context = ContextColumns::from_rows(&rows)?;
        let width = STATE_FEATURES.len() + context.width();
        let mut features = vec![0.0; rows.len() * width];
        for (row, values) in rows.iter().zip(features.chunks_exact_mut(width)) {
            for (column, name) in STATE_FEATURES.iter().enumerate() {
                values[column] = numeric_feature(&row[*name]);
            }
            context.write_row(row, &mut values[STATE_FEATURES.len()..])?;
        }
        Ok(Self {
            features: Array2::from_shape_vec((rows.len(), width), features)
                .map_err(|error| Error::new(error.to_string()))?,
            treatment: rows
                .iter()
                .map(|row| Ok(f64::from(integer(row, "item_id")? == treatment)))
                .collect::<Result<_>>()?,
            outcome: rows
                .iter()
                .map(|row| {
                    row["won"]
                        .as_bool()
                        .map(f64::from)
                        .ok_or_else(|| Error::new("Contrast outcome must be a boolean"))
                })
                .collect::<Result<_>>()?,
            matches: rows
                .iter()
                .map(|row| integer(row, "match_id"))
                .collect::<Result<_>>()?,
            periods: rows
                .iter()
                .map(|row| deadlock_data::text(row, "fold").map(str::to_owned))
                .collect::<Result<_>>()?,
        })
    }

    pub fn select(&self, indices: &[usize]) -> Self {
        Self {
            features: self.features.select(Axis(0), indices),
            treatment: indices.iter().map(|index| self.treatment[*index]).collect(),
            outcome: indices.iter().map(|index| self.outcome[*index]).collect(),
            matches: indices.iter().map(|index| self.matches[*index]).collect(),
            periods: indices
                .iter()
                .map(|index| self.periods[*index].clone())
                .collect(),
        }
    }

    pub fn match_folds(&self) -> Result<Vec<usize>> {
        let matches = self
            .matches
            .iter()
            .copied()
            .collect::<BTreeSet<_>>()
            .into_iter()
            .collect::<Vec<_>>();
        if matches.len() < 2 {
            return Err(Error::new(
                "Cross-fitting requires at least two match groups",
            ));
        }
        self.matches
            .iter()
            .map(|identity| {
                matches
                    .binary_search(identity)
                    .map(|index| index % matches.len().min(5))
                    .map_err(|_| Error::new("Match group index is missing"))
            })
            .collect()
    }
}
