use std::collections::BTreeMap;

use deadlock_data::{Error, Result, object};
use serde_json::{Map, Value, json};

use crate::mechanics_text::{is_populated, normalize_mechanical_value};

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CategoryBonus {
    pub threshold: u64,
    pub values: Map<String, Value>,
}

#[derive(Clone, Debug)]
pub struct CategoryBonusTable(BTreeMap<String, Vec<CategoryBonus>>);

impl CategoryBonusTable {
    /// # Errors
    /// Returns an error when authoritative bonuses are absent or contain invalid or duplicate thresholds.
    pub fn from_asset(asset: &Value) -> Result<Self> {
        let mut categories = BTreeMap::new();
        for (category, rows) in object(&asset["cost_bonuses"])? {
            if categories
                .insert(category.to_lowercase(), parse_bonuses(rows)?)
                .is_some()
            {
                return Err(Error::new("Cost bonus categories must be unique"));
            }
        }
        Ok(Self(categories))
    }

    #[must_use]
    pub const fn categories(&self) -> &BTreeMap<String, Vec<CategoryBonus>> {
        &self.0
    }

    /// # Errors
    /// Returns an error when cumulative category expenditure decreases.
    pub fn crossed(
        &self,
        category: &str,
        previous_spend: u64,
        new_spend: u64,
    ) -> Result<Vec<&CategoryBonus>> {
        if new_spend < previous_spend {
            return Err(Error::new(
                "Cumulative category expenditure must not decrease",
            ));
        }
        Ok(self
            .0
            .get(&category.to_lowercase())
            .into_iter()
            .flatten()
            .filter(|bonus| previous_spend < bonus.threshold && bonus.threshold <= new_spend)
            .collect())
    }
}

fn parse_bonuses(rows: &Value) -> Result<Vec<CategoryBonus>> {
    let rows = match rows {
        Value::Object(rows) => rows
            .iter()
            .map(|(threshold, value)| json!({"threshold":threshold,"value":value}))
            .collect(),
        Value::Array(rows) => rows.clone(),
        _ => return Err(Error::new("Cost bonuses must be an object or an array")),
    };
    let mut bonuses = rows.iter().map(parse_bonus).collect::<Result<Vec<_>>>()?;
    bonuses.sort_by_key(|bonus| bonus.threshold);
    if bonuses
        .windows(2)
        .any(|pair| pair[0].threshold == pair[1].threshold)
    {
        return Err(Error::new("Cost bonus thresholds must be unique"));
    }
    Ok(bonuses)
}

fn parse_bonus(row: &Value) -> Result<CategoryBonus> {
    let row = object(row)?;
    let threshold = ["gold_threshold", "threshold", "cost"]
        .iter()
        .find_map(|name| row.get(*name))
        .and_then(|value| {
            value.as_u64().or_else(|| {
                value
                    .as_str()
                    .filter(|text| text.bytes().all(|byte| byte.is_ascii_digit()))?
                    .parse()
                    .ok()
            })
        })
        .ok_or_else(|| Error::new("Cost bonus threshold must be a nonnegative integer"))?;
    let values = row
        .iter()
        .filter(|(name, value)| {
            !["gold_threshold", "threshold", "cost"].contains(&name.as_str()) && is_populated(value)
        })
        .map(|(name, value)| (name.clone(), normalize_mechanical_value(value)))
        .collect();
    Ok(CategoryBonus { threshold, values })
}
