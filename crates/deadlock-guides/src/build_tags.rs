use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Error, Result};
use deadlock_input::{AXIS_CLASSES, BuildTagCatalog, FUNCTION_CLASSES};
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::guide_item::GuideItem;

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct BuildTagSelection {
    pub tag_ids: [u64; 3],
    pub class_names: [String; 3],
    pub labels: [String; 3],
    pub archetype: String,
}

/// # Errors
/// Returns an error when the ability order, core icon, or pinned tag catalog has an invalid identity.
pub fn select_build_tags(
    ability_path: &[u64],
    core: &[GuideItem],
    assets: &[Value],
    catalog: &BuildTagCatalog,
) -> Result<BuildTagSelection> {
    let assets = assets
        .iter()
        .filter_map(|asset| asset["id"].as_u64().map(|id| (id, asset)))
        .collect::<BTreeMap<_, _>>();
    if core.is_empty() || core.iter().any(|item| !assets.contains_key(&item.item_id)) {
        return Err(Error::new("Core items are missing from pinned assets"));
    }
    let ability_id = first_maxed_ability(ability_path)?;
    let ability = assets
        .get(&ability_id)
        .ok_or_else(|| Error::new("First completed ability is missing from pinned assets"))?;
    let icon = core
        .iter()
        .filter_map(|item| match item.tier {
            3 => Some((0, item)),
            4 => Some((1, item)),
            2 => Some((2, item)),
            1 => Some((3, item)),
            _ => None,
        })
        .min_by_key(|(priority, item)| (*priority, item.item_id))
        .map(|(_, item)| item)
        .ok_or_else(|| Error::new("Core has no supported item tier for its icon"))?;
    let (ability_class, ability_label) = asset_identity(ability)?;
    let (item_class, item_label) = asset_identity(assets[&icon.item_id])?;
    let (axis, function) = classify_core(core, &assets)?;
    let axis = catalog.require(axis)?;
    let function = catalog.require(function)?;
    let archetype = if function.class_name == "citadel_build_tag_damage" {
        format!("{} Damage", axis.label)
    } else {
        format!("{} / {}", function.label, axis.label)
    };
    let tag_ids = [ability_id, icon.item_id, function.tag_id];
    if tag_ids.into_iter().collect::<BTreeSet<_>>().len() != 3 {
        return Err(Error::new("Selected build icons are not distinct"));
    }
    Ok(BuildTagSelection {
        tag_ids,
        class_names: [ability_class, item_class, function.class_name.clone()],
        labels: [ability_label, item_label, function.label.clone()],
        archetype,
    })
}

fn asset_identity(asset: &Value) -> Result<(String, String)> {
    let class_name = deadlock_data::text(asset, "class_name")?.trim();
    let label = deadlock_data::text(asset, "name")?.trim();
    if class_name.is_empty() || label.is_empty() {
        return Err(Error::new("Selected icon has no asset identity"));
    }
    Ok((class_name.into(), label.into()))
}

fn first_maxed_ability(path: &[u64]) -> Result<u64> {
    let mut counts = BTreeMap::<u64, usize>::new();
    for id in path {
        *counts.entry(*id).or_default() += 1;
    }
    if path.len() != 16
        || counts.len() != 4
        || counts.contains_key(&0)
        || counts.values().any(|count| *count != 4)
    {
        return Err(Error::new(
            "Ability path is not a complete four-ability path",
        ));
    }
    counts.clear();
    for id in path {
        let count = counts.entry(*id).or_default();
        *count += 1;
        if *count == 4 {
            return Ok(*id);
        }
    }
    Err(Error::new("Ability path does not complete an ability"))
}

fn asset_text(value: &Value) -> String {
    match value {
        Value::Object(fields) => fields
            .iter()
            .map(|(key, value)| format!("{key} {}", asset_text(value)))
            .collect::<Vec<_>>()
            .join(" "),
        Value::Array(values) => values.iter().map(asset_text).collect::<Vec<_>>().join(" "),
        Value::String(value) => value.clone(),
        Value::Null | Value::Bool(_) | Value::Number(_) => String::new(),
    }
}

fn classify_function(asset: &Value) -> usize {
    let text = asset_text(asset).to_lowercase();
    let rules: &[(usize, &[&str])] = &[
        (
            7,
            &["healing reduction", "heal amp receive penalty", "anti-heal"],
        ),
        (6, &["headshot", "head shot"]),
        (5, &["melee", "heavy punch"]),
        (
            3,
            &[
                "stun",
                "immobil",
                "silence",
                "disarm",
                "knockdown",
                "slowpercent",
            ],
        ),
        (4, &["move speed", "dash", "teleport", "leap", "sprint"]),
        (2, &["healing", "heal", "lifesteal", "health regen"]),
        (1, &["ally", "shield", "barrier", "cooldown", "active"]),
    ];
    rules
        .iter()
        .find(|(_, terms)| terms.iter().any(|term| text.contains(term)))
        .map_or(0, |(index, _)| *index)
}

fn classify_core(
    core: &[GuideItem],
    assets: &BTreeMap<u64, &Value>,
) -> Result<(&'static str, &'static str)> {
    let mut axes = [0_u64; 3];
    let mut functions = [0_u64; 8];
    for item in core {
        let asset = assets[&item.item_id];
        let cost = asset
            .get("cost")
            .filter(|value| !value.is_null())
            .map_or(Ok(0), |value| {
                value
                    .as_u64()
                    .ok_or_else(|| Error::new("Item cost must be a nonnegative integer"))
            })?;
        let slot = asset["item_slot_type"]
            .as_str()
            .unwrap_or_default()
            .to_lowercase();
        if let Some(index) = ["weapon", "spirit", "vitality"]
            .iter()
            .position(|expected| *expected == slot)
        {
            add_cost(&mut axes[index], cost)?;
        }
        add_cost(&mut functions[classify_function(asset)], cost)?;
    }
    Ok((
        AXIS_CLASSES[first_maximum(&axes)],
        FUNCTION_CLASSES[first_maximum(&functions)],
    ))
}

fn add_cost(total: &mut u64, amount: u64) -> Result<()> {
    *total = total
        .checked_add(amount)
        .ok_or_else(|| Error::new("Build tag cost exceeds 64 bits"))?;
    Ok(())
}

fn first_maximum(values: &[u64]) -> usize {
    values
        .iter()
        .enumerate()
        .min_by_key(|(index, value)| (std::cmp::Reverse(*value), *index))
        .map_or(0, |(index, _)| index)
}
