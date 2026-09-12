use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Result, integer};
use deadlock_input::ItemGraph;
use serde::Deserialize;
use serde_json::{Value, json};

use crate::database::{AnalysisDatabase, Parameters};
use crate::inventory_history::{Actor, Purchase, inventory_before};
use crate::sql_resources::load_sql;

type Histories = BTreeMap<u64, BTreeMap<u64, (u64, Vec<Purchase>)>>;

#[derive(Debug, Deserialize)]
struct TeamPurchase {
    team_id: u64,
    #[serde(flatten)]
    purchase: Purchase,
}

pub fn load_checkpoints(
    database: &AnalysisDatabase,
    hero: u64,
    graph: &ItemGraph,
    minimum: u16,
    maximum: u16,
) -> Result<Vec<Value>> {
    let parameters = Parameters::from([
        ("hero".into(), duckdb::types::Value::UBigInt(hero)),
        ("minimum".into(), i64::from(minimum).into()),
        ("maximum".into(), i64::from(maximum).into()),
    ]);
    let mut histories = Histories::new();
    database.visit_rows(
        load_sql("discovery/select_purchase_event_histories.sql")?,
        &parameters,
        |row: TeamPurchase| {
            let purchase = row.purchase;
            histories
                .entry(purchase.match_id)
                .or_default()
                .entry(purchase.player_slot)
                .or_insert_with(|| (row.team_id, Vec::new()))
                .1
                .push(purchase);
            Ok(())
        },
    )?;
    let mut decisions = Vec::new();
    let mut enemy_cache = BTreeMap::<(u64, u64, u64), Vec<u64>>::new();
    let mut previous_match = None;
    database.visit_rows(
        load_sql("discovery/select_decision_rows.sql")?,
        &parameters,
        |mut row: Value| {
            let actor: Actor = (integer(&row, "match_id")?, integer(&row, "player_slot")?);
            let team = integer(&row, "team_id")?;
            let clock = integer(&row, "buy_time")?;
            if previous_match != Some(actor.0) {
                enemy_cache.clear();
                previous_match = Some(actor.0);
            }
            let inventory = histories
                .get(&actor.0)
                .and_then(|players| players.get(&actor.1))
                .map_or(&[][..], |(_, purchases)| purchases.as_slice());
            row["owned_before"] = json!(inventory_before(inventory, graph, i64::try_from(clock)?)?);
            let enemy_observed = row["enemy_observed"]
                .as_u64()
                .filter(|observed| fresh(clock, *observed));
            row["enemy_items"] = json!(
                enemy_observed
                    .map(|observed| {
                        let key = (actor.0, team, observed);
                        if let std::collections::btree_map::Entry::Vacant(entry) =
                            enemy_cache.entry(key)
                        {
                            entry.insert(enemy_inventory(
                                histories.get(&actor.0),
                                team,
                                observed,
                                graph,
                            )?);
                        }
                        Ok::<_, deadlock_data::Error>(enemy_cache[&key].clone())
                    })
                    .transpose()?
                    .unwrap_or_default()
            );
            if enemy_observed.is_none() {
                row["enemy_heroes"] = json!([]);
            }
            row["relative_wealth"] = relative_wealth(&row, clock).into();
            row["fold"] = if row["partition"] == "discovery" {
                "train"
            } else {
                "validation"
            }
            .into();
            retain_contrast_fields(&mut row)?;
            decisions.push(row);
            Ok(())
        },
    )?;
    Ok(decisions)
}

fn enemy_inventory(
    players: Option<&BTreeMap<u64, (u64, Vec<Purchase>)>>,
    team: u64,
    observed: u64,
    graph: &ItemGraph,
) -> Result<Vec<u64>> {
    let mut result = BTreeSet::new();
    for (owner, purchases) in players
        .into_iter()
        .flat_map(|players| players.values())
        .filter(|(owner, _)| *owner != team)
    {
        let _ = owner;
        result.extend(inventory_before(
            purchases,
            graph,
            i64::try_from(observed)?.saturating_add(1),
        )?);
    }
    Ok(result.into_iter().collect())
}

fn fresh(clock: u64, observed: u64) -> bool {
    clock
        .checked_sub(observed)
        .is_some_and(|age| (1..=300).contains(&age))
}

fn relative_wealth(row: &Value, clock: u64) -> Option<f64> {
    let complete = row["own_team_observed_players"] == 6
        && row["enemy_team_observed_players"] == 6
        && row["own_observed"]
            .as_u64()
            .is_some_and(|observed| fresh(clock, observed))
        && row["enemy_observed"]
            .as_u64()
            .is_some_and(|observed| fresh(clock, observed));
    let total = row["own_team_net_worth"].as_f64().unwrap_or(0.0)
        + row["enemy_team_net_worth"].as_f64().unwrap_or(0.0);
    if complete && total > 0.0 {
        row["own_net_worth_at_buy"]
            .as_f64()
            .map(|wealth| wealth * 12.0 / total)
    } else {
        None
    }
}

fn retain_contrast_fields(row: &mut Value) -> Result<()> {
    let fields = row
        .as_object_mut()
        .ok_or_else(|| deadlock_data::Error::new("Decision row must be an object"))?;
    fields.retain(|key, _| {
        key.starts_with("context_")
            || [
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
                "match_id",
                "player_slot",
                "item_id",
                "won",
                "fold",
                "enemy_heroes",
                "enemy_items",
                "owned_before",
                "relative_wealth",
            ]
            .contains(&key.as_str())
    });
    Ok(())
}
