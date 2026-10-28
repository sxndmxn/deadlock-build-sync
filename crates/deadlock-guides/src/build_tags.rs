use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Error, Result};
use deadlock_input::{BuildTagCatalog, FUNCTION_CLASSES, clean_mechanical_text};
use serde_json::Value;

/// One CORE item for tag selection: the item ID and its shop tier.
#[derive(Clone, Copy, Debug)]
pub struct TagItem {
    pub item_id: u64,
    pub tier: u8,
}

#[derive(Clone, Debug)]
pub struct BuildTagSelection {
    pub tag_ids: [u64; 3],
    /// The name of the first fully upgraded ability.
    pub ability_name: String,
}

/// # Errors
/// Returns an error when the ability order, core icon, or pinned tag catalog has an invalid identity.
pub fn select_build_tags(
    ability_path: &[u64],
    core: &[TagItem],
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
    let ability_id = first_fully_upgraded_ability(ability_path)?;
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
    let ability_name = select_asset_name(ability)?;
    select_asset_name(assets[&icon.item_id])?;
    let function = catalog.require(classify_core(core, &assets)?)?;
    let tag_ids = [ability_id, icon.item_id, function.tag_id];
    if tag_ids.into_iter().collect::<BTreeSet<_>>().len() != 3 {
        return Err(Error::new("Selected build icons are not distinct"));
    }
    Ok(BuildTagSelection {
        tag_ids,
        ability_name,
    })
}

/// Returns the asset name, after a check that the asset has a class and a name.
fn select_asset_name(asset: &Value) -> Result<String> {
    let class_name = deadlock_data::text(asset, "class_name")?.trim();
    let name = deadlock_data::text(asset, "name")?.trim();
    if class_name.is_empty() || name.is_empty() {
        return Err(Error::new("Selected icon has no asset identity"));
    }
    Ok(name.into())
}

pub fn first_fully_upgraded_ability(path: &[u64]) -> Result<u64> {
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

fn classify_function(asset: &Value) -> usize {
    let text = format!(
        "{} {}",
        extract_description_text(&asset["name"]),
        extract_description_text(&asset["description"])
    )
    .to_lowercase();
    let rules: &[(usize, &[&str])] = &[
        (
            7,
            &["healing reduction", "heal amp receive penalty", "anti-heal"],
        ),
        (6, &["headshot", "head shot"]),
        (
            5,
            &[
                "melee attack",
                "melee damage",
                "heavy melee",
                "light melee",
                "heavy punch",
            ],
        ),
        (
            3,
            &[
                "stun",
                "stuns",
                "stunned",
                "immobilize",
                "immobilizes",
                "immobilized",
                "silence",
                "silences",
                "disarm",
                "disarms",
                "knockdown",
                "slow",
                "slows",
                "slowing",
            ],
        ),
        (
            4,
            &[
                "move speed",
                "movement speed",
                "dash",
                "dashes",
                "teleport",
                "teleports",
                "leap",
                "leaps",
                "sprint",
            ],
        ),
        (
            2,
            &[
                "healing",
                "heal",
                "heals",
                "lifesteal",
                "life steal",
                "regen",
            ],
        ),
        (
            1,
            &["ally", "allies", "shield", "barrier", "cooldown", "active"],
        ),
    ];
    rules
        .iter()
        .find(|(_, terms)| terms.iter().any(|term| contains_effect_phrase(&text, term)))
        .map_or(0, |(index, _)| *index)
}

fn contains_effect_phrase(text: &str, phrase: &str) -> bool {
    text.match_indices(phrase).any(|(start, matched)| {
        text[..start]
            .chars()
            .next_back()
            .is_none_or(|character| !character.is_alphanumeric())
            && text[start + matched.len()..]
                .chars()
                .next()
                .is_none_or(|character| !character.is_alphanumeric())
    })
}

/// Returns the function tag class with the largest CORE item cost. The first class wins a tie.
fn classify_core(core: &[TagItem], assets: &BTreeMap<u64, &Value>) -> Result<&'static str> {
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
        let total = &mut functions[classify_function(asset)];
        *total = total
            .checked_add(cost)
            .ok_or_else(|| Error::new("Build tag cost exceeds 64 bits"))?;
    }
    let index = functions
        .iter()
        .enumerate()
        .min_by_key(|(index, value)| (std::cmp::Reverse(**value), *index))
        .map_or(0, |(index, _)| index);
    Ok(FUNCTION_CLASSES[index])
}

fn extract_description_text(value: &Value) -> String {
    match value {
        Value::Null => String::new(),
        Value::Object(fields) => fields
            .values()
            .map(extract_description_text)
            .collect::<Vec<_>>()
            .join(" "),
        Value::Array(values) => values
            .iter()
            .map(extract_description_text)
            .collect::<Vec<_>>()
            .join(" "),
        Value::String(_) => clean_mechanical_text(value),
        Value::Bool(value) => if *value { "True" } else { "False" }.into(),
        Value::Number(value) => value.to_string(),
    }
}
