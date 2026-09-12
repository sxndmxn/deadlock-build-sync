use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Error, Result, object};
use serde_json::Value;

const INDICATORS: [(&str, &str); 3] = [
    ("enemy_heroes", "context_enemy_heroes_"),
    ("enemy_items", "context_enemy_items_"),
    ("owned_before", "context_owned_before_"),
];

#[derive(Debug)]
pub struct ContextColumns {
    width: usize,
    numeric: Vec<(usize, String)>,
    indicators: [BTreeMap<u64, Vec<usize>>; 3],
}

impl ContextColumns {
    pub fn from_rows(rows: &[&Value]) -> Result<Self> {
        let names = context_names(rows)?;
        let mut columns = Self {
            width: names.len(),
            numeric: Vec::new(),
            indicators: std::array::from_fn(|_| BTreeMap::new()),
        };
        for (column, name) in names.into_iter().enumerate() {
            if let Some((family, item)) = indicator(&name)? {
                columns.indicators[family]
                    .entry(item)
                    .or_default()
                    .push(column);
            } else {
                let field = if name == "context_relative_wealth" {
                    "relative_wealth".into()
                } else {
                    name
                };
                columns.numeric.push((column, field));
            }
        }
        Ok(columns)
    }

    pub const fn width(&self) -> usize {
        self.width
    }

    pub fn write_row(&self, row: &Value, output: &mut [f64]) -> Result<()> {
        for (column, field) in &self.numeric {
            if field != "relative_wealth" && row[field].is_array() {
                return Err(Error::new("Numeric contrast context cannot be an array"));
            }
            output[*column] = numeric_feature(&row[field]);
        }
        for (family, (field, _)) in INDICATORS.iter().enumerate() {
            if let Some(values) = row[*field].as_array() {
                for value in values {
                    let item = item_identifier(value)?;
                    if let Some(columns) = self.indicators[family].get(&item) {
                        for column in columns {
                            output[*column] = 1.0;
                        }
                    }
                }
            }
        }
        Ok(())
    }
}

fn context_names(rows: &[&Value]) -> Result<BTreeSet<String>> {
    let mut fields = BTreeSet::new();
    let mut items: [BTreeSet<u64>; 3] = std::array::from_fn(|_| BTreeSet::new());
    let mut wealth = false;
    for row in rows {
        fields.extend(
            object(row)?
                .keys()
                .filter(|name| name.starts_with("context_"))
                .map(String::as_str),
        );
        for (family, (field, _)) in INDICATORS.iter().enumerate() {
            if let Some(values) = row[*field].as_array() {
                for value in values {
                    items[family].insert(item_identifier(value)?);
                }
            }
        }
        wealth |= !row["relative_wealth"].is_null();
    }
    let mut names = fields
        .into_iter()
        .map(str::to_owned)
        .collect::<BTreeSet<_>>();
    for (family, (_, prefix)) in INDICATORS.iter().enumerate() {
        names.extend(items[family].iter().map(|item| format!("{prefix}{item}")));
    }
    if wealth {
        names.insert("context_relative_wealth".into());
    }
    Ok(names)
}

fn indicator(name: &str) -> Result<Option<(usize, u64)>> {
    for (family, (_, prefix)) in INDICATORS.iter().enumerate() {
        if let Some(item) = name.strip_prefix(prefix) {
            return item
                .parse()
                .map(|item| Some((family, item)))
                .map_err(|error: std::num::ParseIntError| Error::new(error.to_string()));
        }
    }
    Ok(None)
}

fn item_identifier(value: &Value) -> Result<u64> {
    value
        .as_u64()
        .ok_or_else(|| Error::new("Contrast context has an invalid item identifier"))
}

pub fn numeric_feature(value: &Value) -> f64 {
    value
        .as_f64()
        .or_else(|| value.as_bool().map(f64::from))
        .unwrap_or(f64::NAN)
}
