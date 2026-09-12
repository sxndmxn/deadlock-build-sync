use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::Result;
use deadlock_input::clean_mechanical_text;
use serde_json::Value;

use crate::mechanic_patterns::{
    ally_target, control_immunity, offensive_response, positive_resistance,
};
use crate::mechanic_properties::{mechanics_text, observed_text, response_properties};
use crate::threat::Threat;

const RESPONSE_RULES: [(&str, &str, &str); 18] = [
    ("spirit resist", "Spirit Resist", "spirit_burst"),
    ("spirit shield", "Spirit Shield", "spirit_burst"),
    ("debuff resist", "Debuff Resist", "hard_control"),
    ("debuff immunity", "Debuff Immunity", "hard_control"),
    ("control immunity", "Control Immunity", "hard_control"),
    ("unstoppable", "Unstoppable", "hard_control"),
    ("bullet resist", "Bullet Resist", "bullet_pressure"),
    ("bullet shield", "Bullet Shield", "bullet_pressure"),
    (
        "weapon damage resistance",
        "Weapon Damage Resistance",
        "bullet_pressure",
    ),
    ("healing reduction", "Healing Reduction", "healing"),
    ("reduce healing", "Healing Reduction", "healing"),
    ("anti-heal", "Healing Reduction", "healing"),
    (
        "remove all negative",
        "Negative Effect Removal",
        "hard_control",
    ),
    ("slow immunity", "Slow Immunity", "slow_resistance"),
    (
        "movement slow resistance",
        "Movement Slow Resist",
        "slow_resistance",
    ),
    ("ground", "Ground", "mobility_denial"),
    ("disarm", "Disarm", "mobility_denial"),
    ("movement slow", "Movement Slow", "mobility_denial"),
];

const OBSERVED_RULES: [(Threat, &[&str]); 6] = [
    (Threat::BulletPressure, &["bullet damage", "weapon damage"]),
    (Threat::SpiritPressure, &["spirit damage", "spirit power"]),
    (
        Threat::Control,
        &[
            "apply a stun",
            "applies a stun",
            "silences the target",
            "immobilizes",
            "become rooted",
        ],
    ),
    (
        Threat::MobilityEscape,
        &["dash", "teleport", "leap", "blink"],
    ),
    (
        Threat::MobilityDenial,
        &[
            "applies a movement slow",
            "applies movement slow",
            "become grounded",
            "causes grounded",
        ],
    ),
    (
        Threat::AllyProtection,
        &[
            "target ally",
            "allied target",
            "shield an ally",
            "ally barrier",
        ],
    ),
];

/// # Errors
/// Returns an error when the asset identity or a fixed mechanics pattern is invalid.
pub fn classify_response_mechanic_labels(asset: &Value) -> Result<BTreeMap<String, Vec<String>>> {
    let text = observed_text(asset)?;
    let mut labels = property_labels(asset)?;
    for (phrase, response, label) in [
        ("bullet resist", "bullet_pressure", "Bullet Resist"),
        ("spirit resist", "spirit_burst", "Spirit Resist"),
    ] {
        if positive_resistance(&text, phrase)? {
            add_label(&mut labels, response, label);
        }
    }
    if control_immunity(&text)? {
        add_label(&mut labels, "hard_control", "Control Immunity");
    }
    for (phrase, label, response) in RESPONSE_RULES {
        if valid_response_phrase(&text, phrase)? {
            add_label(&mut labels, response, label);
        }
    }
    if ally_target(&text)? && contains_any(&text, &["shield", "heal", "resist"]) {
        add_label(&mut labels, "ally_protection", "Ally Protection");
    }
    Ok(labels)
}

fn valid_response_phrase(text: &str, phrase: &str) -> Result<bool> {
    if !text.contains(phrase) {
        return Ok(false);
    }
    match phrase {
        "bullet resist" | "spirit resist" => positive_resistance(text, phrase),
        "ground" | "disarm" | "movement slow" => offensive_response(text, phrase),
        _ => Ok(true),
    }
}

fn add_label(labels: &mut BTreeMap<String, Vec<String>>, response: &str, label: &str) {
    let values = labels.entry(response.into()).or_default();
    if !values.iter().any(|value| value == label) {
        values.push(label.into());
    }
}

fn property_labels(asset: &Value) -> Result<BTreeMap<String, Vec<String>>> {
    let mut labels = BTreeMap::new();
    for property in response_properties(asset).values() {
        if let Some((response, label)) = property_response(property)? {
            add_label(&mut labels, response, &label);
        }
    }
    Ok(labels)
}

fn property_response(property: &Value) -> Result<Option<(&'static str, String)>> {
    let property_type = property["provided_property_type"]
        .as_str()
        .unwrap_or_default()
        .to_uppercase();
    if property_type.contains("RESIST_REDUCTION") {
        return Ok(None);
    }
    let label = clean_mechanical_text(&property["label"]);
    for (pattern, response, default_label, use_label) in [
        (
            "BULLET_ARMOR_DAMAGE_RESIST",
            "bullet_pressure",
            "Bullet Resist",
            false,
        ),
        ("BULLET_SHIELD", "bullet_pressure", "Bullet Shield", true),
        ("FIRE_RATE_SLOW", "bullet_pressure", "Fire Rate Slow", false),
        (
            "SPIRIT_ARMOR_DAMAGE_RESIST",
            "spirit_burst",
            "Spirit Resist",
            false,
        ),
        ("SPIRIT_SHIELD", "spirit_burst", "Spirit Shield", true),
    ] {
        if property_type.contains(pattern) {
            return Ok(Some((
                response,
                if use_label && !label.is_empty() {
                    label
                } else {
                    default_label.into()
                },
            )));
        }
    }
    let normalized = mechanics_text(property)?;
    for (phrase, response, default_label) in [
        ("bullet shield", "bullet_pressure", "Bullet Shield"),
        ("spirit shield", "spirit_burst", "Spirit Shield"),
    ] {
        if normalized.contains(phrase) {
            return Ok(Some((
                response,
                if label.is_empty() {
                    default_label.into()
                } else {
                    label
                },
            )));
        }
    }
    Ok(None)
}

pub fn contains_any(text: &str, phrases: &[&str]) -> bool {
    phrases.iter().any(|phrase| text.contains(phrase))
}

/// # Errors
/// Returns an error when the asset identity or a fixed mechanics pattern is invalid.
pub fn classify_item_threat_responses(asset: &Value) -> Result<BTreeSet<String>> {
    Ok(classify_response_mechanic_labels(asset)?
        .into_keys()
        .collect())
}

/// # Errors
/// Returns an error when the observed item has an invalid asset identity.
pub fn classify_observed_item_threats(asset: &Value) -> Result<BTreeSet<Threat>> {
    let text = observed_text(asset)?;
    let mut threats = OBSERVED_RULES
        .into_iter()
        .filter(|(_, phrases)| contains_any(&text, phrases))
        .map(|(threat, _)| threat)
        .collect::<BTreeSet<_>>();
    if contains_any(
        &text,
        &[
            "restore health",
            "health regen",
            "healing amp",
            "heal an ally",
        ],
    ) && !contains_any(&text, &["healing reduction", "reduce healing", "anti-heal"])
    {
        threats.insert(Threat::Healing);
    }
    Ok(threats)
}
