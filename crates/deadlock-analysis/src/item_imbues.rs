use std::collections::BTreeMap;

use deadlock_data::Result;
use deadlock_guides::{HeroBuild, ImbueTarget};
use serde::Deserialize;
use serde_json::Value;

use crate::database::{AnalysisDatabase, Parameters};
use crate::sql_resources::load_sql;

#[derive(Debug, Deserialize)]
struct ItemImbueRow {
    hero_id: u64,
    item_id: u64,
    ability_id: u64,
    target_matches: u64,
    observations: u64,
}

pub type ItemImbues = BTreeMap<(u64, u64), ImbueTarget>;

pub fn load_item_imbues(
    database: &AnalysisDatabase,
    parameters: &Parameters,
) -> Result<ItemImbues> {
    Ok(database
        .query_rows::<ItemImbueRow>(
            load_sql("builds/select_item_imbue_targets.sql")?,
            parameters,
        )?
        .into_iter()
        .map(|row| {
            (
                (row.hero_id, row.item_id),
                ImbueTarget {
                    ability_id: row.ability_id,
                    matches: row.target_matches,
                    observations: row.observations,
                },
            )
        })
        .collect())
}

pub fn attach_item_imbues(build: &mut HeroBuild, targets: &ItemImbues, assets: &[Value]) {
    for item in build.core.iter_mut().chain(&mut build.situational) {
        item.imbue_target = targets
            .get(&(build.hero_id, item.item_id))
            .filter(|target| {
                target.validate().is_ok()
                    && build.ability_ids.contains(&target.ability_id)
                    && is_current_target(build.hero_id, item.item_id, target.ability_id, assets)
            })
            .cloned();
    }
}

fn is_current_target(hero_id: u64, item_id: u64, ability_id: u64, assets: &[Value]) -> bool {
    let asset = |id| assets.iter().find(|asset| asset["id"].as_u64() == Some(id));
    let (Some(item), Some(ability)) = (asset(item_id), asset(ability_id)) else {
        return false;
    };
    let belongs_to_hero = ability["hero"].as_u64() == Some(hero_id)
        || ability["heroes"]
            .as_array()
            .is_some_and(|heroes| heroes.iter().any(|hero| hero.as_u64() == Some(hero_id)));
    if item["type"] != "upgrade"
        || ability["type"] != "ability"
        || !belongs_to_hero
        || !matches!(
            ability["ability_type"].as_str(),
            Some("signature" | "ultimate")
        )
    {
        return false;
    }
    match item["imbue"].as_str() {
        Some("imbue_active_non_ult") => ability["ability_type"] != "ultimate",
        Some("imbue_active" | "imbue_modifier_value") => true,
        _ => false,
    }
}
