use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Error, Result, count_ratio, integer, real};
use serde_json::{Value, json};

use crate::database::{AnalysisDatabase, Parameters};
use crate::inventory_history::Actor;
use crate::purchase_pool::replace_members;
use crate::sql_resources::load_sql;

pub fn load_item_metrics(
    database: &AnalysisDatabase,
    members: &BTreeSet<Actor>,
    hero: u64,
    assets: &BTreeMap<u64, Value>,
    folds: &Value,
) -> Result<(Vec<Value>, Value)> {
    replace_members(database, "_build_path_members", members)?;
    let parameters = Parameters::from([
        ("hero".into(), duckdb::types::Value::UBigInt(hero)),
        ("minimum_support".into(), 20_i64.into()),
        (
            "member_count".into(),
            duckdb::types::Value::UBigInt(u64::try_from(members.len())?),
        ),
    ]);
    let items = database
        .query(
            load_sql("production/select_path_item_metrics.sql")?,
            &parameters,
        )?
        .iter()
        .map(|row| item_payload(row, assets, folds))
        .collect::<Result<Vec<_>>>()?;
    let summary = database
        .query(
            load_sql("production/select_path_cohort_summary.sql")?,
            &Parameters::new(),
        )?
        .into_iter()
        .next()
        .ok_or_else(|| Error::new("Build path has no cohort summary"))?;
    Ok((items, summary))
}

fn item_payload(row: &Value, assets: &BTreeMap<u64, Value>, folds: &Value) -> Result<Value> {
    let mut result = serde_json::Map::new();
    for (target, source) in [
        ("item", "item_name"),
        ("eligible_player_matches", "hero_player_matches"),
        ("adoption", "adoption_rate"),
        ("observed_outcome_rate", "raw_outcome_rate"),
        ("buy_net_worth_q25", "buy_nw_q25"),
        ("buy_net_worth_q75", "buy_nw_q75"),
        ("valid_buy_net_worth_share", "valid_buy_nw_share"),
        ("selection_buy_net_worth_q25", "selection_buy_nw_q25"),
        ("selection_buy_net_worth_q75", "selection_buy_nw_q75"),
        (
            "selection_valid_buy_net_worth_observations",
            "selection_valid_buy_nw_observations",
        ),
        (
            "training_valid_buy_net_worth_observations",
            "training_valid_buy_nw_observations",
        ),
        (
            "validation_valid_buy_net_worth_observations",
            "validation_valid_buy_nw_observations",
        ),
        ("training_buy_net_worth_q25", "training_buy_nw_q25"),
        ("training_buy_net_worth_q75", "training_buy_nw_q75"),
        ("validation_buy_net_worth_q25", "validation_buy_nw_q25"),
        ("validation_buy_net_worth_q75", "validation_buy_nw_q75"),
    ] {
        result.insert(target.into(), row[source].clone());
    }
    for field in [
        "item_id",
        "tier",
        "cost",
        "slot",
        "active",
        "adopter_matches",
        "purchase_events",
        "wins",
        "median_buy_time_s",
        "median_valid_buy_net_worth",
        "selection_median_buy_time_s",
        "selection_median_valid_buy_net_worth",
    ] {
        result.insert(field.into(), row[field].clone());
    }
    let training = integer(folds, "train")?;
    let validation = integer(folds, "validation")?;
    for (name, population) in [
        ("training", training),
        ("validation", validation),
        ("test", integer(folds, "test")?),
        ("selection", training + validation),
    ] {
        let adopters = integer(row, &format!("{name}_adopter_matches"))?;
        result.insert(format!("{name}_adopter_matches"), adopters.into());
        result.insert(format!("{name}_eligible_player_matches"), population.into());
        result.insert(
            format!("{name}_adoption"),
            count_ratio(adopters, population.max(1))?.into(),
        );
    }
    result.insert(
        "selection_valid_buy_net_worth_share".into(),
        count_ratio(
            integer(row, "selection_valid_buy_nw_observations")?,
            integer(row, "selection_adopter_matches")?.max(1),
        )?
        .into(),
    );
    let mut result = Value::Object(result);
    let imbue = imbue_fields(row, assets)?;
    for (key, value) in deadlock_data::object(&imbue)? {
        result[key] = value.clone();
    }
    Ok(result)
}

fn imbue_fields(row: &Value, assets: &BTreeMap<u64, Value>) -> Result<Value> {
    let target = row["imbued_ability_id"].as_u64();
    let name = target
        .and_then(|item| assets.get(&item))
        .and_then(|item| item["name"].as_str())
        .map(str::trim)
        .filter(|name| !name.is_empty());
    let matches = row["target_matches"].as_u64().unwrap_or(0);
    let observations = row["imbue_observations"].as_u64().unwrap_or(0);
    let share = if row["target_share"].is_null() {
        0.0
    } else {
        real(row, "target_share")?
    };
    let supported = name.is_some() && matches >= 20 && share > 0.5;
    Ok(
        json!({"imbue_target_ability_id":target.filter(|_|supported),"imbue_target_ability":name.filter(|_|supported),
        "imbue_target_matches":if supported {matches}else{0},"imbue_observations":if supported {observations}else{0},"imbue_target_share":if supported{share}else{0.0}}),
    )
}
