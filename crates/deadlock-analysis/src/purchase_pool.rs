use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Error, Result, count_ratio};
use deadlock_guides::{
    PurchasePriorities, PurchaseState, SUPPORT, nondecreasing_window_schedule, plan_purchases,
    schedule_component_path,
};
use deadlock_input::ItemGraph;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

use crate::database::{AnalysisDatabase, Parameters};
use crate::discovery_data::DiscoveryData;
use crate::inventory_history::MatchPlayer;
use crate::sql_resources::load_sql;

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
struct ItemPoolStatistics {
    item_id: u64,
    #[serde(flatten)]
    statistics: PoolStatistics,
}

pub fn replace_members(
    database: &AnalysisDatabase,
    name: &str,
    members: &BTreeSet<MatchPlayer>,
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
    members: &BTreeSet<MatchPlayer>,
    hero: u64,
) -> Result<PurchaseEvidence> {
    replace_members(database, "_discovery_buyers", members)?;
    let population = u64::try_from(members.len())?;
    database.execute(
        load_sql("discovery/create_item_pool_purchases.sql")?,
        &Parameters::from([("hero".into(), duckdb::types::Value::UBigInt(hero))]),
    )?;
    let items = database
        .query_rows::<ItemPoolStatistics>(
            load_sql("discovery/select_item_pool_statistics.sql")?,
            &Parameters::from([(
                "population".into(),
                duckdb::types::Value::UBigInt(population.max(1)),
            )]),
        )?
        .into_iter()
        .map(|row| (row.item_id, row.statistics))
        .collect();
    Ok(PurchaseEvidence { population, items })
}

pub fn build_guide_snapshot(
    database: &AnalysisDatabase,
    data: &DiscoveryData,
    core: &[u64],
    order: &[u64],
    graph: &ItemGraph,
) -> Result<FrozenGuide> {
    let evidence =
        load_purchase_evidence(database, &data.owners(core, &["discovery"])?, data.hero)?;
    let (priorities, bounds) = timing_policy(&evidence.items)?;
    let path = schedule_component_path(graph, order, &priorities)?;
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
                .is_none_or(|item_statistics| item_statistics.buyers < SUPPORT.pool_buyers)
        })
        .collect::<Vec<_>>();
    if !missing.is_empty() {
        return Err(Error::new(format!(
            "Component purchase records are incomplete: {missing:?}"
        )));
    }
    let pool = select_pool(graph, &evidence, &path);
    let optional_items = pool.values().flatten().copied().collect::<BTreeSet<_>>();
    let timing = database.query(
        load_sql("discovery/select_purchase_checkpoint_counts.sql")?,
        &Parameters::from([
            ("path".into(), serde_json::to_string(&path)?.into()),
            (
                "items".into(),
                serde_json::to_string(&optional_items)?.into(),
            ),
        ]),
    )?;
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
    for (item, item_statistics) in statistics {
        let reliable = item_statistics.fresh_wealth_observations >= 20
            && count_ratio(
                item_statistics.fresh_wealth_observations,
                item_statistics.buyers.max(1),
            )? >= 0.5;
        let wealth = item_statistics.net_worth_q25_q50_q75.filter(|_| reliable);
        priorities.insert(
            *item,
            (
                wealth.map_or(f64::INFINITY, |wealth| wealth[1]),
                item_statistics.time_seconds_q25_q50_q75[1],
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
        .filter(|(item, item_statistics)| {
            graph.nodes().contains_key(item)
                && !path.contains(item)
                && item_statistics.buyers >= SUPPORT.pool_buyers
        })
        .map(|(item, item_statistics)| (*item, item_statistics.buyers))
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
