use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Error, Result};
use deadlock_input::is_populated;
use serde_json::{Value, json};

use crate::mechanic_properties::mechanics_text;
use crate::mechanic_responses::contains_any;

pub const MECHANIC_TAGS: [(&str, u32, &[&str]); 11] = [
    (
        "melee",
        3,
        &["melee attack", "melee damage", "heavy melee", "light melee"],
    ),
    (
        "charges",
        2,
        &["ability charge", "+1 charge", "charge delay"],
    ),
    (
        "healing",
        2,
        &["heal", "healing", "lifesteal", "life steal"],
    ),
    (
        "range",
        1,
        &["ability range", "increased range", "cast range", "radius"],
    ),
    ("cooldown", 1, &["cooldown", "recharge time"]),
    (
        "slow",
        1,
        &["movement slow", "move speed slow", "applies slow"],
    ),
    ("stun", 1, &["stun", "stunned", "knockup"]),
    ("bullet_resist", 1, &["bullet resist", "bullet resistance"]),
    ("spirit_resist", 1, &["spirit resist", "spirit resistance"]),
    ("weapon_damage", 1, &["weapon damage", "bullet damage"]),
    ("spirit_damage", 1, &["spirit damage"]),
];

/// # Errors
/// Returns an error when the asset identifier is not a positive integer.
pub fn asset_mechanics_refs(asset: &Value) -> Result<Vec<String>> {
    let id = asset["id"]
        .as_u64()
        .filter(|id| *id > 0)
        .ok_or_else(|| Error::new("Asset mechanics reference requires a positive identifier"))?;
    let prefix = format!("asset:item:{id}");
    let mut references = vec![prefix.clone()];
    for (field, suffix) in [
        ("description", "description"),
        ("component_items", "components"),
    ] {
        if is_populated(&asset[field]) && asset[field] != false && asset[field] != 0 {
            references.push(format!("{prefix}:{suffix}"));
        }
    }
    Ok(references)
}

/// # Errors
/// Returns an error when asset text cannot serialize.
pub fn hero_item_affinity_scores(hero: &Value, assets: &[Value]) -> Result<BTreeMap<u64, u32>> {
    let Some(signatures) = hero["items"].as_object() else {
        return Ok(BTreeMap::new());
    };
    let classes = assets
        .iter()
        .filter_map(|asset| asset["class_name"].as_str().map(|class| (class, asset)))
        .collect::<BTreeMap<_, _>>();
    let abilities = signatures
        .values()
        .filter_map(Value::as_str)
        .filter_map(|class| classes.get(class))
        .map(|asset| name_and_description(asset))
        .collect::<Vec<_>>();
    let tags = mechanic_tags(&abilities.into())?;
    let mut scores = BTreeMap::new();
    for asset in assets {
        let Some(id) = asset["id"].as_u64().filter(|id| *id > 0) else {
            continue;
        };
        let item_tags = mechanic_tags(&name_and_description(asset))?;
        let score = MECHANIC_TAGS
            .into_iter()
            .filter(|(tag, _, _)| tags.contains(tag) && item_tags.contains(tag))
            .map(|(_, weight, _)| weight)
            .sum::<u32>();
        if score > 0 {
            scores.insert(id, score);
        }
    }
    Ok(scores)
}

fn name_and_description(asset: &Value) -> Value {
    json!({"name":asset["name"], "description":asset["description"]})
}

fn mechanic_tags(value: &Value) -> Result<BTreeSet<&'static str>> {
    let text = mechanics_text(value)?;
    Ok(MECHANIC_TAGS
        .into_iter()
        .filter(|(_, _, phrases)| contains_any(&text, phrases))
        .map(|(tag, _, _)| tag)
        .collect())
}
