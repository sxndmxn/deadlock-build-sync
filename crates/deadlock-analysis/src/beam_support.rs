use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Result, count_ratio};
use deadlock_guides::wilson_score_interval;
use deadlock_input::ItemGraph;
use serde_json::{Value, json};

use crate::discovery_data::DiscoveryData;

pub type CoreGroups = BTreeMap<String, Vec<BTreeSet<u64>>>;

#[derive(Debug)]
pub struct BeamOwnership {
    exact: BTreeMap<u64, Vec<u64>>,
    expanded: BTreeMap<u64, Vec<u64>>,
    eligible: Vec<u64>,
}

impl BeamOwnership {
    pub fn new(data: &DiscoveryData, graph: &ItemGraph, state: u8) -> Result<Self> {
        let words = data.rows.len().div_ceil(64);
        let mut result = Self {
            exact: BTreeMap::new(),
            expanded: BTreeMap::new(),
            eligible: vec![0; words],
        };
        for index in data
            .fold_rows("discovery")
            .filter(|index| wealth_state(data.rows[*index].relative_wealth) == Some(state))
        {
            let word = index / 64;
            let bit = 1 << (index % 64);
            result.eligible[word] |= bit;
            for item in &data.inventories[index] {
                result.exact.entry(*item).or_insert_with(|| vec![0; words])[word] |= bit;
                for component in std::iter::once(item).chain(graph.transitive_components(*item)?) {
                    result
                        .expanded
                        .entry(*component)
                        .or_insert_with(|| vec![0; words])[word] |= bit;
                }
            }
        }
        Ok(result)
    }

    pub fn count(&self, core: &[u64], expanded: bool) -> u64 {
        let columns = if expanded {
            &self.expanded
        } else {
            &self.exact
        };
        if core.iter().any(|item| !columns.contains_key(item)) {
            return 0;
        }
        self.eligible
            .iter()
            .enumerate()
            .map(|(index, eligible)| {
                u64::from(
                    core.iter()
                        .fold(*eligible, |bits, item| bits & columns[item][index])
                        .count_ones(),
                )
            })
            .sum()
    }
}

pub fn wealth_state(value: Option<f64>) -> Option<u8> {
    value
        .filter(|value| value.is_finite() && *value > 0.0)
        .map(|value| {
            if value < 0.9 {
                0
            } else if value > 1.1 {
                2
            } else {
                1
            }
        })
}

pub fn assign_core_group(core: &[u64], groups: &CoreGroups) -> Result<Option<String>> {
    let core = core.iter().copied().collect::<BTreeSet<_>>();
    let existing = groups
        .iter()
        .filter(|(_, members)| members.contains(&core))
        .map(|(group, _)| group)
        .collect::<Vec<_>>();
    if !existing.is_empty() {
        return Ok((existing.len() == 1).then(|| existing[0].clone()));
    }
    let mut eligible = Vec::new();
    for (group, members) in groups {
        let mut matched = true;
        for member in members {
            let shared = core.intersection(member).count();
            if shared < 2
                || count_ratio(
                    u64::try_from(shared)?,
                    u64::try_from(core.union(member).count())?,
                )? < 0.5
            {
                matched = false;
                break;
            }
        }
        if matched {
            eligible.push(group.clone());
        }
    }
    Ok((eligible.len() == 1).then(|| eligible[0].clone()))
}

pub fn state_statistics(data: &DiscoveryData, core: &[u64], state: u8) -> Result<Value> {
    let mut result = json!({});
    for fold in ["discovery", "selection", "validation"] {
        let eligible = data
            .fold_rows(fold)
            .filter(|index| wealth_state(data.rows[*index].relative_wealth) == Some(state))
            .collect::<Vec<_>>();
        let owners = eligible
            .iter()
            .filter(|index| {
                core.iter()
                    .all(|item| data.inventories[**index].contains(item))
            })
            .collect::<Vec<_>>();
        let count = u64::try_from(owners.len())?;
        let wins = u64::try_from(
            owners
                .iter()
                .filter(|index| data.rows[***index].won)
                .count(),
        )?;
        let total = u64::try_from(eligible.len())?;
        let hero_wins = u64::try_from(
            eligible
                .iter()
                .filter(|index| data.rows[**index].won)
                .count(),
        )?;
        let (lower, upper) = wilson_score_interval(wins, count, 1.96)?;
        result[fold] = json!({"owners":count,"wins":wins,"win_rate":if count>0{Some(count_ratio(wins,count)?)}else{None},
            "lower_95":if count>0{Some(lower)}else{None},"upper_95":if count>0{Some(upper)}else{None},
            "hero_matches":total,"hero_win_rate":if total>0{Some(count_ratio(hero_wins,total)?)}else{None},"ownership_before_seconds":1200});
    }
    Ok(result)
}
