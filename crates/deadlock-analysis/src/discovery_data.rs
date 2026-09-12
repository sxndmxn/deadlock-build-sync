use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Error, RankRange, Result};
use deadlock_input::ItemGraph;
use serde::Deserialize;

use crate::database::{AnalysisDatabase, Parameters};
use crate::inventory_history::{Actor, Purchase, inventory_before};
use crate::sql_resources::load_sql;

#[derive(Clone, Debug, Deserialize)]
pub struct Landmark {
    pub match_id: u64,
    pub player_slot: u64,
    #[serde(rename = "partition")]
    pub fold: String,
    pub won: bool,
    pub observed_wealth: Option<f64>,
    pub team_lead: Option<f64>,
    pub average_badge: u16,
    pub relative_wealth: Option<f64>,
}

#[derive(Clone, Debug)]
pub struct DiscoveryData {
    pub hero: u64,
    pub items: Vec<u64>,
    pub times: Vec<Vec<i64>>,
    pub rows: Vec<Landmark>,
    pub inventories: Vec<Vec<u64>>,
}

impl DiscoveryData {
    pub fn fold_rows<'a>(&'a self, fold: &'a str) -> impl Iterator<Item = usize> + 'a {
        self.rows
            .iter()
            .enumerate()
            .filter(move |(_, row)| row.fold == fold)
            .map(|(index, _)| index)
    }

    pub fn columns(&self, items: &[u64]) -> Result<Vec<usize>> {
        items
            .iter()
            .map(|item| {
                self.items
                    .binary_search(item)
                    .map_err(|_| Error::new("Core contains an item outside the discovery matrix"))
            })
            .collect()
    }

    pub fn owns(&self, row: usize, columns: &[usize]) -> bool {
        columns.iter().all(|column| self.times[row][*column] >= 0)
    }

    pub fn owners(&self, items: &[u64], folds: &[&str]) -> Result<BTreeSet<Actor>> {
        let columns = self.columns(items)?;
        Ok(self
            .rows
            .iter()
            .enumerate()
            .filter(|(index, row)| {
                folds.contains(&row.fold.as_str()) && self.owns(*index, &columns)
            })
            .map(|(_, row)| (row.match_id, row.player_slot))
            .collect())
    }
}

pub fn prepare_partitions(database: &AnalysisDatabase) -> Result<()> {
    let fixed = database.count(
        load_sql("discovery/count_split_boundaries.sql")?,
        &Parameters::new(),
    )? == 1;
    let query = if fixed {
        "discovery/create_fixed_partitions.sql"
    } else {
        "discovery/create_ranked_partitions.sql"
    };
    database.execute(load_sql(query)?, &Parameters::new())
}

pub fn load_discovery_data(
    database: &AnalysisDatabase,
    hero: u64,
    graph: &ItemGraph,
    ranks: RankRange,
) -> Result<DiscoveryData> {
    let parameters = Parameters::from([("hero".into(), duckdb::types::Value::UBigInt(hero))]);
    if database.count(
        load_sql("discovery/count_hero_appearances.sql")?,
        &parameters,
    )? == 0
    {
        return Err(Error::new(format!(
            "Hero {hero} has no source data; run refresh-evidence"
        )));
    }
    let mut parameters = parameters;
    parameters.insert("ownership_before_seconds".into(), 1200_i64.into());
    let rows = database
        .query_rows::<Landmark>(load_sql("discovery/select_landmark_rows.sql")?, &parameters)?
        .into_iter()
        .filter(|row| (ranks.minimum.badge()..=ranks.maximum.badge()).contains(&row.average_badge))
        .collect::<Vec<_>>();
    let mut histories = BTreeMap::<Actor, Vec<Purchase>>::new();
    database.visit_rows(
        load_sql("discovery/select_purchase_histories.sql")?,
        &parameters,
        |purchase: Purchase| {
            histories
                .entry((purchase.match_id, purchase.player_slot))
                .or_default()
                .push(purchase);
            Ok(())
        },
    )?;
    build_discovery_data(hero, rows, &histories, graph)
}

fn build_discovery_data(
    hero: u64,
    rows: Vec<Landmark>,
    histories: &BTreeMap<Actor, Vec<Purchase>>,
    graph: &ItemGraph,
) -> Result<DiscoveryData> {
    if rows
        .iter()
        .map(|row| row.match_id)
        .collect::<BTreeSet<_>>()
        .len()
        != rows.len()
    {
        return Err(Error::new(
            "Discovery contains duplicate hero appearances in a match",
        ));
    }
    let inventories = rows
        .iter()
        .map(|row| {
            inventory_before(
                histories
                    .get(&(row.match_id, row.player_slot))
                    .map_or(&[], Vec::as_slice),
                graph,
                1200,
            )
        })
        .collect::<Result<Vec<_>>>()?;
    let mut support = BTreeMap::<u64, usize>::new();
    for (row, owned) in rows
        .iter()
        .zip(&inventories)
        .filter(|(row, _)| row.fold == "discovery")
    {
        let _ = row;
        let mut distinct = owned.clone();
        distinct.sort_unstable();
        distinct.dedup();
        for item in distinct {
            *support.entry(item).or_default() += 1;
        }
    }
    let minimum = rows
        .iter()
        .filter(|row| row.fold == "discovery")
        .count()
        .div_ceil(100)
        .max(100);
    let items = support
        .into_iter()
        .filter(|(_, count)| *count >= minimum)
        .map(|(item, _)| Ok((item, graph.require(item)?.cost)))
        .collect::<Result<Vec<_>>>()?
        .into_iter()
        .filter(|(_, cost)| *cost >= 1600)
        .map(|(item, _)| item)
        .collect::<Vec<_>>();
    let mut times = vec![vec![-1; items.len()]; rows.len()];
    for (index, row) in rows.iter().enumerate() {
        for purchase in histories
            .get(&(row.match_id, row.player_slot))
            .map_or(&[][..], Vec::as_slice)
        {
            if let Ok(column) = items.binary_search(&purchase.item_id)
                && inventories[index].contains(&purchase.item_id)
            {
                times[index][column] = times[index][column].max(purchase.buy_time);
            }
        }
    }
    Ok(DiscoveryData {
        hero,
        items,
        times,
        rows,
        inventories,
    })
}
