use std::collections::BTreeMap;

use deadlock_data::{Result, count_as_f64, count_ratio};
use deadlock_input::ItemGraph;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

use crate::discovery_data::DiscoveryData;

type SupportCounts = BTreeMap<Vec<usize>, u64>;
type VerticalColumns = Vec<(usize, Vec<u64>)>;

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Candidate {
    pub items: Vec<u64>,
    pub names: Vec<String>,
    pub cost: u64,
    pub discovery_support: u64,
    pub discovery_lift: f64,
    pub score: f64,
    pub parent: Vec<u64>,
    pub parent_retention: Option<f64>,
    #[serde(default)]
    pub identity_id: String,
    #[serde(default)]
    pub selection: Value,
    #[serde(default)]
    pub selection_rejections: Vec<String>,
}

#[derive(Debug)]
pub struct MiningResult {
    pub candidates: Vec<Candidate>,
    pub sizes: Value,
}

pub fn mine_candidates(data: &DiscoveryData, graph: &ItemGraph) -> Result<MiningResult> {
    let rows = data.fold_rows("discovery").collect::<Vec<_>>();
    let mut result = MiningResult {
        candidates: Vec::new(),
        sizes: json!({}),
    };
    if rows.is_empty() {
        return Ok(result);
    }
    let columns = vertical_columns(data, &rows);
    let marginal = (0..data.items.len())
        .map(|column| {
            count_ratio(
                u64::try_from(
                    rows.iter()
                        .filter(|row| data.times[**row][column] >= 0)
                        .count(),
                )?,
                u64::try_from(rows.len())?,
            )
        })
        .collect::<Result<Vec<_>>>()?;
    let mut previous = SupportCounts::new();
    for length in 3..=6 {
        let mut raw = SupportCounts::new();
        enumerate_itemsets(&[], &columns, length, &mut raw);
        let mut qualified = SupportCounts::new();
        let mut candidates = Vec::new();
        for (indices, count) in &raw {
            if let Some(candidate) = qualify(
                data,
                graph,
                &marginal,
                &previous,
                indices,
                *count,
                u64::try_from(rows.len())?,
            )? {
                qualified.insert(indices.clone(), *count);
                candidates.push(candidate);
            }
        }
        candidates.sort_by(|left, right| {
            right
                .score
                .total_cmp(&left.score)
                .then_with(|| left.items.cmp(&right.items))
        });
        candidates.truncate(50);
        result.sizes[length.to_string()] =
            json!({"frequent":raw.len(),"qualified":qualified.len(),"retained":candidates.len()});
        result.candidates.extend(candidates);
        previous = qualified;
    }
    Ok(result)
}

fn vertical_columns(data: &DiscoveryData, rows: &[usize]) -> VerticalColumns {
    (0..data.items.len())
        .filter_map(|column| {
            let mut bits = vec![0_u64; rows.len().div_ceil(64)];
            for (index, row) in rows.iter().enumerate() {
                if data.times[*row][column] >= 0 {
                    bits[index / 64] |= 1 << (index % 64);
                }
            }
            (population(&bits) >= 100).then_some((column, bits))
        })
        .collect()
}

fn population(bits: &[u64]) -> u64 {
    bits.iter().map(|value| u64::from(value.count_ones())).sum()
}

fn enumerate_itemsets(
    prefix: &[usize],
    columns: &VerticalColumns,
    length: usize,
    output: &mut SupportCounts,
) {
    for (position, (column, bits)) in columns.iter().enumerate() {
        if prefix.len() + columns.len() - position < length {
            break;
        }
        let mut next = prefix.to_vec();
        next.push(*column);
        if next.len() == length {
            output.insert(next, population(bits));
            continue;
        }
        let suffix = columns[position + 1..]
            .iter()
            .filter_map(|(following, other)| {
                let intersection = bits
                    .iter()
                    .zip(other)
                    .map(|(left, right)| left & right)
                    .collect::<Vec<_>>();
                (population(&intersection) >= 100).then_some((*following, intersection))
            })
            .collect();
        enumerate_itemsets(&next, &suffix, length, output);
    }
}

fn qualify(
    data: &DiscoveryData,
    graph: &ItemGraph,
    marginal: &[f64],
    previous: &SupportCounts,
    columns: &[usize],
    count: u64,
    rows: u64,
) -> Result<Option<Candidate>> {
    let items = columns
        .iter()
        .map(|column| data.items[*column])
        .collect::<Vec<_>>();
    let assets = items
        .iter()
        .map(|item| graph.require(*item))
        .collect::<Result<Vec<_>>>()?;
    let cost = assets.iter().map(|item| item.cost).sum::<u64>();
    if cost > 19200 || assets.iter().any(|item| item.cost < 1600) {
        return Ok(None);
    }
    for item in &items {
        if graph
            .transitive_components(*item)?
            .iter()
            .any(|ancestor| items.contains(ancestor))
        {
            return Ok(None);
        }
    }
    let Some(parent) = supported_parent(columns, count, previous) else {
        return Ok(None);
    };
    let expected = columns
        .iter()
        .map(|column| marginal[*column])
        .product::<f64>();
    let lift = count_ratio(count, rows)? / expected;
    if lift < 1.1 {
        return Ok(None);
    }
    Ok(Some(Candidate {
        names: assets.iter().map(|item| item.name.clone()).collect(),
        items,
        cost,
        discovery_support: count,
        discovery_lift: lift,
        score: count_ratio(count, rows)? * lift.ln(),
        parent: parent.iter().map(|column| data.items[*column]).collect(),
        parent_retention: if parent.is_empty() {
            None
        } else {
            Some(count_as_f64(count)? / count_as_f64(previous[&parent])?)
        },
        identity_id: String::new(),
        selection: Value::Null,
        selection_rejections: Vec::new(),
    }))
}

fn supported_parent(columns: &[usize], count: u64, previous: &SupportCounts) -> Option<Vec<usize>> {
    if columns.len() == 3 {
        return Some(Vec::new());
    }
    (0..columns.len())
        .map(|removed| {
            columns
                .iter()
                .enumerate()
                .filter(|(index, _)| *index != removed)
                .map(|(_, column)| *column)
                .collect::<Vec<_>>()
        })
        .filter(|parent| {
            previous
                .get(parent)
                .is_some_and(|support| count >= support.div_ceil(2))
        })
        .min()
}
