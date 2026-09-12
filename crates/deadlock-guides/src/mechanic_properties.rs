use std::collections::BTreeMap;

use deadlock_data::{Result, canonical_json};
use deadlock_input::{extract_asset_mechanics, is_populated, normalize_mechanical_value};
use serde_json::{Map, Value};

const PROPERTY_FIELDS: [&str; 9] = [
    "css_class",
    "label",
    "postvalue_label",
    "provided_property_type",
    "tooltip_is_elevated",
    "tooltip_is_important",
    "tooltip_section",
    "usage_flags",
    "value",
];

pub fn response_properties(asset: &Value) -> BTreeMap<&str, Value> {
    asset["properties"]
        .as_object()
        .into_iter()
        .flatten()
        .filter_map(|(name, property)| {
            let value = property.get("value")?;
            if !active_property(property, value)
                || property["tooltip_is_important"] != true
                || resistance_reduction(name, property)
            {
                return None;
            }
            let fields = PROPERTY_FIELDS
                .into_iter()
                .filter_map(|key| {
                    property
                        .get(key)
                        .map(|value| (key.to_owned(), value.clone()))
                })
                .collect::<Map<_, _>>();
            Some((name.as_str(), fields.into()))
        })
        .collect()
}

fn active_property(property: &Value, value: &Value) -> bool {
    if value.is_null() || ["", "0", "0.0"].contains(&property_text(value).as_str()) {
        return false;
    }
    property
        .get("disable_value")
        .filter(|value| !value.is_null())
        .is_none_or(|disabled| property_text(value) != property_text(disabled))
}

fn resistance_reduction(name: &str, property: &Value) -> bool {
    let identity = format!(
        "{name} {} {}",
        property_text(&property["label"]),
        property_text(&property["provided_property_type"])
    )
    .to_lowercase();
    identity.contains("resist")
        && (identity.contains("reduction") || property_text(&property["value"]).starts_with('-'))
}

fn property_text(value: &Value) -> String {
    match value {
        Value::Null => String::new(),
        Value::String(value) => value.clone(),
        Value::Bool(value) => if *value { "True" } else { "False" }.into(),
        value => value.to_string(),
    }
}

pub fn observed_mechanics(asset: &Value) -> Result<Value> {
    let mechanics = extract_asset_mechanics(asset)?;
    let mut observed = Map::new();
    let description = base_description(&asset["description"]);
    if is_populated(&description) {
        observed.insert(
            "description".into(),
            normalize_mechanical_value(&description),
        );
    }
    for key in ["behaviour", "damage_type", "targeting", "weapon_info"] {
        if let Some(value) = mechanics.get(key) {
            observed.insert(key.into(), value.clone());
        }
    }
    let properties = response_properties(asset);
    if !properties.is_empty() {
        observed.insert(
            "properties".into(),
            normalize_mechanical_value(&serde_json::to_value(properties)?),
        );
    }
    Ok(observed.into())
}

fn base_description(description: &Value) -> Value {
    if description.is_object() {
        ["desc", "passive", "active"]
            .into_iter()
            .filter_map(|key| {
                description
                    .get(key)
                    .filter(|value| is_populated(value))
                    .map(|value| (key.to_owned(), value.clone()))
            })
            .collect::<Map<_, _>>()
            .into()
    } else {
        description.clone()
    }
}

pub fn mechanics_text(value: &Value) -> Result<String> {
    Ok(std::str::from_utf8(&canonical_json(value)?)?.to_lowercase())
}

pub fn observed_text(asset: &Value) -> Result<String> {
    mechanics_text(&observed_mechanics(asset)?)
}
