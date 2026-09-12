use std::collections::BTreeSet;
use std::sync::LazyLock;

use deadlock_data::{Error, Result};
use deadlock_input::clean_mechanical_text;
use regex_lite::Regex;
use serde_json::Value;

use crate::purchase_effect_rules::{CONDITION_RULES, EFFECT_RULES, STAT_RULES};
use crate::purchase_guidance_types::ItemPurpose;

static EFFECT_PATTERNS: LazyLock<Result<Vec<Regex>>> =
    LazyLock::new(|| compile_patterns(EFFECT_RULES.iter().map(|(pattern, _, _)| *pattern)));
static CONDITION_PATTERNS: LazyLock<Result<Vec<Regex>>> =
    LazyLock::new(|| compile_patterns(CONDITION_RULES.iter().map(|(pattern, _)| *pattern)));

fn compile_patterns<'pattern>(patterns: impl Iterator<Item = &'pattern str>) -> Result<Vec<Regex>> {
    patterns
        .map(|pattern| {
            Regex::new(pattern)
                .map_err(|error| Error::new(format!("Invalid item effect pattern: {error}")))
        })
        .collect()
}

#[must_use]
pub fn extract_description_text(value: &Value) -> String {
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

#[must_use]
pub fn extract_primary_effect_text(asset: &Value) -> String {
    let mut parts = vec![extract_description_text(&asset["description"])];
    for section in object_rows(&asset["tooltip_sections"])
        .filter(|section| section["section_type"] != "innate")
    {
        for row in object_rows(&section["section_attributes"]) {
            parts.push(extract_description_text(&row["loc_string"]));
        }
    }
    let mut seen = BTreeSet::new();
    parts.retain(|part| !part.is_empty() && seen.insert(part.clone()));
    parts.join(" ").trim().into()
}

fn object_rows(value: &Value) -> impl Iterator<Item = &Value> {
    value
        .as_array()
        .filter(|rows| rows.iter().all(Value::is_object))
        .into_iter()
        .flatten()
}

#[must_use]
pub fn extract_important_statistics(asset: &Value) -> BTreeSet<String> {
    let mut keys = BTreeSet::new();
    for section in object_rows(&asset["tooltip_sections"]) {
        for row in object_rows(&section["section_attributes"]) {
            for field in ["important_properties", "elevated_properties"] {
                keys.extend(
                    row[field]
                        .as_array()
                        .into_iter()
                        .flatten()
                        .filter_map(Value::as_str)
                        .map(str::to_owned),
                );
            }
        }
    }
    keys.retain(|key| {
        let value = &asset["properties"][key]["value"];
        if value.is_null() {
            return false;
        }
        let rendered = value
            .as_str()
            .map_or_else(|| value.to_string(), str::to_owned);
        !["None", "0", "0.0", "-1", ""].contains(&rendered.as_str())
    });
    keys
}

/// # Errors
/// Returns an error when a fixed item effect pattern cannot compile.
pub fn classify_item_purpose(asset: &Value) -> Result<ItemPurpose> {
    let text = extract_primary_effect_text(asset);
    let normalized = normalize_effect_text(&text);
    let patterns = EFFECT_PATTERNS
        .as_ref()
        .map_err(|error| Error::new(error.to_string()))?;
    let conditions = CONDITION_PATTERNS
        .as_ref()
        .map_err(|error| Error::new(error.to_string()))?;
    for (pattern, (_, label, trigger)) in patterns.iter().zip(EFFECT_RULES) {
        if let Some(found) = pattern.find(&normalized) {
            let trigger = conditions
                .iter()
                .zip(CONDITION_RULES)
                .find(|(pattern, _)| pattern.is_match(&normalized))
                .map_or(*trigger, |(_, (_, trigger))| *trigger);
            return Ok(ItemPurpose {
                label: (*label).into(),
                trigger: trigger.into(),
                evidence: found.as_str().into(),
                basis: "primary effect text".into(),
            });
        }
    }
    if text.is_empty()
        && let Some(purpose) = classify_statistics(asset)
    {
        return Ok(purpose);
    }
    Ok(ItemPurpose {
        label: "General utility".into(),
        trigger: if text.is_empty() {
            "Main effect is unknown; follow the core".into()
        } else {
            text.clone()
        },
        evidence: text,
        basis: "unclassified".into(),
    })
}

fn normalize_effect_text(text: &str) -> String {
    let mut normalized = String::new();
    for character in text.chars().flat_map(char::to_lowercase) {
        if [',', '.'].contains(&character) {
            normalized.truncate(normalized.trim_end().len());
        }
        normalized.push(character);
    }
    normalized
}

fn classify_statistics(asset: &Value) -> Option<ItemPurpose> {
    let keys = extract_important_statistics(asset);
    for (fields, label, trigger) in STAT_RULES {
        let mut matches = fields
            .iter()
            .copied()
            .filter(|field| keys.contains(*field))
            .collect::<Vec<_>>();
        if !matches.is_empty() {
            matches.sort_unstable();
            return Some(ItemPurpose {
                label: (*label).into(),
                trigger: (*trigger).into(),
                evidence: matches.join(", "),
                basis: "material tooltip property".into(),
            });
        }
    }
    None
}
