use std::collections::BTreeMap;

use deadlock_data::Result;
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::mechanic_patterns::ally_target;
use crate::mechanic_properties::observed_text;
use crate::mechanic_responses::{classify_response_mechanic_labels, contains_any};

const RESPONSE_PRIORITY: [&str; 7] = [
    "spirit_burst",
    "bullet_pressure",
    "healing",
    "hard_control",
    "slow_resistance",
    "mobility_denial",
    "ally_protection",
];

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ConditionalItemDecision {
    pub vs: String,
    pub why: String,
    pub when: String,
    pub skip: String,
}

/// # Errors
/// Returns an error when item assets or fixed mechanics patterns are invalid.
pub fn conditional_item_decision(
    asset: &Value,
    comparator: &Value,
    response: Option<&str>,
) -> Result<Option<ConditionalItemDecision>> {
    let labels = classify_response_mechanic_labels(asset)?;
    let selected = response.or_else(|| {
        RESPONSE_PRIORITY
            .into_iter()
            .find(|response| labels.contains_key(*response))
    });
    let Some(selected) = selected.filter(|selected| labels.contains_key(*selected)) else {
        return Ok(None);
    };
    let Some(purpose) = comparator_purpose(&observed_text(comparator)?) else {
        return Ok(None);
    };
    let text = observed_text(asset)?;
    let Some((versus, when)) = response_condition(selected, &text) else {
        return Ok(None);
    };
    Ok(Some(ConditionalItemDecision {
        vs: versus.into(),
        why: describe_mechanics(&labels, selected, &text)?,
        when: when.into(),
        skip: format!("Keep default when {purpose} matters more"),
    }))
}

fn describe_mechanics(
    labels: &BTreeMap<String, Vec<String>>,
    selected: &str,
    text: &str,
) -> Result<String> {
    let mut mechanics = labels.get(selected).cloned().unwrap_or_default();
    for candidate in RESPONSE_PRIORITY {
        if candidate == "ally_protection" && selected != candidate {
            continue;
        }
        for label in labels.get(candidate).into_iter().flatten() {
            if !mechanics.contains(label) {
                mechanics.push(label.clone());
            }
        }
    }
    mechanics.truncate(3);
    let target = if !ally_target(text)? {
        ""
    } else if contains_any(text, &["self cast", "self-cast"]) {
        " for self/ally"
    } else {
        " for ally"
    };
    Ok(format!("{}{target}", mechanics.join(" and ")))
}

fn comparator_purpose(text: &str) -> Option<&'static str> {
    const PURPOSES: [(&[&str], &str); 9] = [
        (&["teleport", "pull", "ground", "disarm"], "catch"),
        (&["bullet resist", "spirit resist", "shield"], "survival"),
        (&["cooldown", "recharge"], "ability uptime"),
        (
            &["weapon damage", "bullet damage", "fire rate"],
            "weapon pressure",
        ),
        (&["spirit damage", "spirit power"], "Spirit pressure"),
        (&["heal", "lifesteal", "life steal"], "sustain"),
        (&["melee"], "melee pressure"),
        (&["range"], "range"),
        (&["slow", "stun", "silence", "root"], "control"),
    ];
    PURPOSES
        .into_iter()
        .find(|(phrases, _)| contains_any(text, phrases))
        .map(|(_, purpose)| purpose)
}

fn response_condition(selected: &str, text: &str) -> Option<(&'static str, &'static str)> {
    Some(match selected {
        "spirit_burst" => ("Heavy Spirit damage", "Before the next Spirit-heavy fight"),
        "bullet_pressure" => ("Heavy bullet damage", "Before the next bullet-heavy fight"),
        "healing" => (
            "Heavy enemy healing",
            "Before the next fight with heavy enemy healing",
        ),
        "hard_control" => (
            "Hard control or debuffs",
            "Before entering the next control-heavy fight",
        ),
        "slow_resistance" => (
            "Enemy slows or movement denial",
            "Before the next fight with heavy slows",
        ),
        "mobility_denial"
            if contains_any(
                text,
                &[
                    "become grounded",
                    "causes grounded",
                    "ground, slow",
                    "disarm",
                    "applies slow",
                ],
            ) =>
        {
            (
                "Enemy escape or mobility",
                "Before fighting an evasive target",
            )
        }
        "mobility_denial" => (
            "Slows or movement denial",
            "Before the next fight with heavy slows",
        ),
        "ally_protection" => (
            "A focused ally needs protection",
            "Before the ally commits to the next fight",
        ),
        _ => return None,
    })
}
