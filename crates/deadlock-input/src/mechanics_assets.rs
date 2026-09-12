use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Error, Result, fingerprint, integer, object, text};
use serde_json::{Map, Value, json};

use crate::mechanics_text::{
    clean_mechanical_text, is_populated, normalize_hero_description, normalize_mechanical_value,
};

pub const MECHANICS_FIELDS: [&str; 26] = [
    "ability_type",
    "behaviour",
    "cast_range",
    "channel_time",
    "component_items",
    "cooldown",
    "cost",
    "cost_bonuses",
    "damage_type",
    "description",
    "duration",
    "imbue",
    "is_active_item",
    "is_unique",
    "item_slot_type",
    "item_tier",
    "level_info",
    "max_count",
    "properties",
    "radius",
    "scaling_stats",
    "targeting",
    "unlock_level",
    "upgrade_costs",
    "upgrades",
    "weapon_info",
];

/// # Errors
/// Returns an error when the asset has no positive numeric identifier.
pub fn extract_asset_mechanics(asset: &Value) -> Result<Value> {
    let id = positive_identifier(asset)?;
    let mut result = object(&json!({
        "id":id,
        "class_name":asset["class_name"].as_str().unwrap_or(""),
        "name":name_or_default(asset, "Asset", id),
        "type":asset["type"].as_str().filter(|name| !name.is_empty()).unwrap_or("unknown"),
    }))?
    .clone();
    copy_mechanics(asset, &mut result, &MECHANICS_FIELDS);
    Ok(result.into())
}

/// # Errors
/// Returns an error when an asset identifier or a signature ability reference is invalid.
pub fn build_hero_mechanics(hero: &Value, assets: &[Value]) -> Result<Value> {
    let id = positive_identifier(hero)?;
    let assets = assets_by_class(assets)?;
    let references = object(&hero["items"])?;
    let abilities = resolve_abilities(references, &assets)?;
    let mut result = object(&json!({
        "hero_id":id,
        "name":name_or_default(hero,"Hero",id),
        "class_name":hero["class_name"].as_str().unwrap_or(""),
        "description":normalize_hero_description(&hero["description"]),
        "abilities":abilities,
    }))?
    .clone();
    copy_mechanics(
        hero,
        &mut result,
        &[
            "scaling_stats",
            "starting_stats",
            "level_info",
            "cost_bonuses",
        ],
    );
    let identity = fingerprint(&Value::Object(result.clone()))?;
    result.insert("mechanics_sha256".into(), identity.into());
    Ok(result.into())
}

fn assets_by_class(assets: &[Value]) -> Result<BTreeMap<&str, &Value>> {
    let mut result = BTreeMap::new();
    for asset in assets {
        if let Some(class_name) = asset["class_name"].as_str()
            && result.insert(class_name, asset).is_some()
        {
            return Err(Error::new(format!(
                "Asset class appears more than once: {class_name}"
            )));
        }
    }
    Ok(result)
}

fn resolve_abilities(
    references: &Map<String, Value>,
    assets: &BTreeMap<&str, &Value>,
) -> Result<Vec<Value>> {
    let mut identities = BTreeSet::new();
    let mut result = Vec::with_capacity(4);
    for slot in 1..=4 {
        let name = references
            .get(&format!("signature{slot}"))
            .and_then(Value::as_str)
            .ok_or_else(|| {
                Error::new(format!("Signature ability {slot} has no asset reference"))
            })?;
        let asset = assets
            .get(name)
            .ok_or_else(|| Error::new(format!("Signature ability asset is absent: {name}")))?;
        let mut ability = extract_asset_mechanics(asset)?;
        if !identities.insert(integer(&ability, "id")?) {
            return Err(Error::new(
                "Signature abilities must have four distinct identifiers",
            ));
        }
        ability["slot"] = slot.into();
        result.push(ability);
    }
    Ok(result)
}

pub fn positive_identifier(value: &Value) -> Result<u64> {
    let id = integer(value, "id")?;
    if id == 0 {
        return Err(Error::new("Asset identifier must be positive"));
    }
    Ok(id)
}

pub fn name_or_default(asset: &Value, prefix: &str, id: u64) -> String {
    let name = clean_mechanical_text(&asset["name"]);
    if name.is_empty() {
        format!("{prefix} {id}")
    } else {
        name
    }
}

fn copy_mechanics(asset: &Value, target: &mut Map<String, Value>, fields: &[&str]) {
    for field in fields {
        if let Some(value) = asset.get(*field).filter(|value| is_populated(value)) {
            target.insert((*field).into(), normalize_mechanical_value(value));
        }
    }
}

pub fn required_class(asset: &Value) -> Result<&str> {
    let name = text(asset, "class_name")?;
    if name.is_empty() {
        return Err(Error::new("Asset class name must not be empty"));
    }
    Ok(name)
}
