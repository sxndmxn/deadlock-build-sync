use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Error, Result, count_as_f64, count_ratio};
use deadlock_guides::{
    PurchasePriorities, PurchaseState, SUPPORT, nondecreasing_window_schedule, plan_purchases,
    schedule_component_path,
};
use deadlock_input::ItemGraph;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

use crate::database::{AnalysisDatabase, Parameters};
use crate::discovery_data::DiscoveryData;
use crate::inventory_history::Actor;
use crate::sql_resources::load_sql;
use crate::statistics::quantiles;

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct PoolStatistics {
    pub buyers: u64,
    pub adoption: f64,
    pub time_seconds_q25_q50_q75: [f64; 3],
    pub fresh_wealth_observations: u64,
    pub net_worth_q25_q50_q75: Option<[f64; 3]>,
}

#[derive(Debug)]
pub struct PurchaseEvidence {
    pub population: u64,
    pub items: BTreeMap<u64, PoolStatistics>,
    pub histories: BTreeMap<Actor, BTreeMap<u64, f64>>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct FrozenGuide {
    pub ready: bool,
    pub reason: Option<String>,
    pub timing_status: String,
    pub path: Vec<u64>,
    pub pool: BTreeMap<u8, Vec<u64>>,
    pub discovery_buyers: u64,
    pub bounds: BTreeMap<u64, (f64, f64)>,
    pub pool_statistics: BTreeMap<u64, PoolStatistics>,
    pub purchase_timing: Value,
}

#[derive(Debug, Deserialize)]
struct FirstPurchase {
    match_id: u64,
    player_slot: u64,
    item_id: u64,
    buy_time: i64,
    own_net_worth_at_buy: Option<f64>,
    state_observed_at_s: Option<i64>,
}

pub fn replace_members(
    database: &AnalysisDatabase,
    name: &str,
    members: &BTreeSet<Actor>,
) -> Result<()> {
    if !["_discovery_buyers", "_build_path_members"].contains(&name) {
        return Err(Error::new("Unknown analysis membership table"));
    }
    database.execute(
        &format!("CREATE OR REPLACE TEMP TABLE {name} (match_id UBIGINT, player_slot UBIGINT)"),
        &Parameters::new(),
    )?;
    let rows = members
        .iter()
        .map(|(match_id, slot)| {
            vec![
                duckdb::types::Value::UBigInt(*match_id),
                duckdb::types::Value::UBigInt(*slot),
            ]
        })
        .collect::<Vec<_>>();
    database.insert_rows(&format!("INSERT INTO {name} VALUES (?, ?)"), &rows)
}

pub fn load_purchase_evidence(
    database: &AnalysisDatabase,
    members: &BTreeSet<Actor>,
    hero: u64,
) -> Result<PurchaseEvidence> {
    replace_members(database, "_discovery_buyers", members)?;
    let mut evidence = PurchaseEvidence {
        population: u64::try_from(members.len())?,
        items: BTreeMap::new(),
        histories: BTreeMap::new(),
    };
    let mut times = BTreeMap::<u64, Vec<f64>>::new();
    let mut wealths = BTreeMap::<u64, Vec<f64>>::new();
    let parameters = Parameters::from([("hero".into(), duckdb::types::Value::UBigInt(hero))]);
    database.visit_rows(
        load_sql("discovery/select_item_pool_purchases.sql")?,
        &parameters,
        |row: FirstPurchase| {
            let bought = count_as_f64(u64::try_from(row.buy_time)?)?;
            if evidence
                .histories
                .entry((row.match_id, row.player_slot))
                .or_default()
                .insert(row.item_id, bought)
                .is_some()
            {
                return Err(Error::new(
                    "First-purchase evidence contains a duplicate player and item",
                ));
            }
            times.entry(row.item_id).or_default().push(bought);
            if let (Some(wealth), Some(observed)) =
                (row.own_net_worth_at_buy, row.state_observed_at_s)
                && (1..=300).contains(&(row.buy_time - observed))
            {
                wealths.entry(row.item_id).or_default().push(wealth);
            }
            Ok(())
        },
    )?;
    if evidence.histories.len() > members.len() {
        return Err(Error::new(
            "Purchase evidence exceeds the discovered owner population",
        ));
    }
    for (item, mut values) in times {
        let wealth = wealths.entry(item).or_default();
        evidence.items.insert(
            item,
            PoolStatistics {
                buyers: u64::try_from(values.len())?,
                adoption: count_ratio(u64::try_from(values.len())?, evidence.population.max(1))?,
                time_seconds_q25_q50_q75: quantiles(&mut values)?
                    .ok_or_else(|| Error::new("Purchase time sample is empty"))?,
                fresh_wealth_observations: u64::try_from(wealth.len())?,
                net_worth_q25_q50_q75: quantiles(wealth)?,
            },
        );
    }
    Ok(evidence)
}

pub fn freeze_guide(
    database: &AnalysisDatabase,
    data: &DiscoveryData,
    core: &[u64],
    order: &[u64],
    graph: &ItemGraph,
    exact_path: Option<&[u64]>,
) -> Result<FrozenGuide> {
    let evidence =
        load_purchase_evidence(database, &data.owners(core, &["discovery"])?, data.hero)?;
    let (priorities, bounds) = timing_policy(&evidence.items)?;
    let path = exact_path.map_or_else(
        || schedule_component_path(graph, order, &priorities),
        |path| Ok(path.to_vec()),
    )?;
    let plan = plan_purchases(
        graph,
        &path,
        core,
        &BTreeMap::new(),
        &PurchaseState::default(),
    )?;
    if !plan
        .actions
        .iter()
        .map(|step| step.item_id)
        .eq(path.iter().copied())
    {
        return Err(Error::new(
            "Component planner differs from the frozen route",
        ));
    }
    let missing = path
        .iter()
        .filter(|item| {
            evidence
                .items
                .get(item)
                .is_none_or(|stats| stats.buyers < SUPPORT.pool_buyers)
        })
        .collect::<Vec<_>>();
    if !missing.is_empty() {
        return Err(Error::new(format!(
            "Component purchase records are incomplete: {missing:?}"
        )));
    }
    let pool = select_pool(graph, &evidence, &path);
    let timing = pool
        .values()
        .flatten()
        .copied()
        .collect::<BTreeSet<_>>()
        .into_iter()
        .map(|item| count_intervals(item, &path, &evidence.histories))
        .collect::<Vec<_>>();
    Ok(FrozenGuide {
        ready: true,
        reason: None,
        timing_status: if nondecreasing_window_schedule(&path, &bounds).is_some() {
            "observed"
        } else {
            "uncertain"
        }
        .into(),
        bounds: bounds
            .into_iter()
            .filter(|(item, _)| path.contains(item))
            .collect(),
        purchase_timing: json!({"version":1,"fold":"train","core_path":path,"items":timing}),
        path,
        pool,
        discovery_buyers: evidence.population,
        pool_statistics: evidence.items,
    })
}

type PurchaseBounds = BTreeMap<u64, (f64, f64)>;

fn timing_policy(
    statistics: &BTreeMap<u64, PoolStatistics>,
) -> Result<(PurchasePriorities, PurchaseBounds)> {
    let mut priorities = BTreeMap::new();
    let mut bounds = BTreeMap::new();
    for (item, stats) in statistics {
        let reliable = stats.fresh_wealth_observations >= 20
            && count_ratio(stats.fresh_wealth_observations, stats.buyers.max(1))? >= 0.5;
        let wealth = stats.net_worth_q25_q50_q75.filter(|_| reliable);
        priorities.insert(
            *item,
            (
                wealth.map_or(f64::INFINITY, |wealth| wealth[1]),
                stats.time_seconds_q25_q50_q75[1],
                *item,
            ),
        );
        if let Some(wealth) = wealth {
            bounds.insert(*item, (wealth[0], wealth[2]));
        }
    }
    Ok((priorities, bounds))
}

fn select_pool(
    graph: &ItemGraph,
    evidence: &PurchaseEvidence,
    path: &[u64],
) -> BTreeMap<u8, Vec<u64>> {
    let mut ranked = evidence
        .items
        .iter()
        .filter(|(item, stats)| {
            graph.nodes().contains_key(item)
                && !path.contains(item)
                && stats.buyers >= SUPPORT.pool_buyers
        })
        .map(|(item, stats)| (*item, stats.buyers))
        .collect::<Vec<_>>();
    ranked.sort_by(|left, right| right.1.cmp(&left.1).then(left.0.cmp(&right.0)));
    (1..=4)
        .map(|tier| {
            let mut items = ranked
                .iter()
                .filter(|(item, _)| graph.nodes()[item].tier == tier)
                .take(SUPPORT.pool_limit)
                .map(|(item, _)| *item)
                .collect::<Vec<_>>();
            items.sort_by(|left, right| {
                evidence.items[left].time_seconds_q25_q50_q75[1]
                    .total_cmp(&evidence.items[right].time_seconds_q25_q50_q75[1])
                    .then(left.cmp(right))
            });
            (tier, items)
        })
        .collect()
}

pub fn count_intervals(
    item: u64,
    path: &[u64],
    histories: &BTreeMap<Actor, BTreeMap<u64, f64>>,
) -> Value {
    let mut counts = vec![0_u64; path.len() + 1];
    let mut buyers = 0_u64;
    for history in histories.values() {
        let Some(bought) = history.get(&item) else {
            continue;
        };
        buyers += 1;
        for (position, count) in counts.iter_mut().enumerate() {
            let left = if position == 0 {
                Some(-1.0)
            } else {
                history.get(&path[position - 1]).copied()
            };
            let right = if position == path.len() {
                Some(f64::INFINITY)
            } else {
                history.get(&path[position]).copied()
            };
            if left
                .zip(right)
                .is_some_and(|(left, right)| left < *bought && *bought < right)
            {
                *count += 1;
            }
        }
    }
    json!({"item_id":item,"buyers":buyers,"counts_by_checkpoint":counts})
}
