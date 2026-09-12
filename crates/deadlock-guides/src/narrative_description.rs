use deadlock_data::{Error, Result};
use serde_json::Value;

pub const MINIMUM_BUILD_DESCRIPTION_CHARACTERS: usize = 80;
pub const MAXIMUM_BUILD_DESCRIPTION_CHARACTERS: usize = 700;

/// # Errors
/// Returns an error when the context has no hero role or cannot produce a description within its length limits.
pub fn build_deterministic_description(context: &Value) -> Result<String> {
    let hero = context["hero"].as_str().unwrap_or_default().trim();
    let descriptions = &context["hero_mechanics"]["description"];
    let role = descriptions["role"]
        .as_str()
        .filter(|role| !role.is_empty())
        .or_else(|| context["policy"]["strategic_role"].as_str())
        .unwrap_or_default()
        .trim();
    if hero.is_empty() || role.is_empty() {
        return Err(Error::new("Description context has no hero role"));
    }
    let role = normalize_sentence(&format!("{hero}: {role}"));
    let archetype = context["projection"]["build"]["archetype"]
        .as_str()
        .unwrap_or_default();
    let mut plan = if archetype.is_empty() {
        "Follow the shown CORE order".into()
    } else {
        format!("Follow the shown {} CORE order", archetype.trim())
    };
    if let Some(ability) = first_maxed_ability(context) {
        write!(plan, " and max {ability} first")?;
    }
    let plan = normalize_sentence(&plan);
    let queue = "Use conditional cards only when their VS line applies; all optional rows stay outside Queue.";
    let playstyle = normalize_sentence(descriptions["playstyle"].as_str().unwrap_or_default());
    let mut description = [role.as_str(), playstyle.as_str(), plan.as_str(), queue]
        .into_iter()
        .filter(|sentence| !sentence.is_empty())
        .collect::<Vec<_>>()
        .join(" ");
    if description.chars().count() > MAXIMUM_BUILD_DESCRIPTION_CHARACTERS {
        description = [role.as_str(), plan.as_str(), queue].join(" ");
    }
    validate_description(&description)?;
    Ok(description)
}

pub fn validate_description(description: &str) -> Result<()> {
    if !(MINIMUM_BUILD_DESCRIPTION_CHARACTERS..=MAXIMUM_BUILD_DESCRIPTION_CHARACTERS)
        .contains(&description.chars().count())
    {
        return Err(Error::new("Build description is outside its length limits"));
    }
    Ok(())
}

fn normalize_sentence(value: &str) -> String {
    let mut value = value
        .split(|character: char| {
            character.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&character)
        })
        .filter(|part| !part.is_empty())
        .collect::<Vec<_>>()
        .join(" ");
    if !value.is_empty() && !value.ends_with(['.', '!', '?']) {
        value.push('.');
    }
    value
}

fn first_maxed_ability(context: &Value) -> Option<&str> {
    context["ability_policy"]["steps"]
        .as_array()?
        .iter()
        .find_map(|step| {
            (step["action"] == "UPGRADE_3")
                .then(|| step["ability"].as_str())
                .flatten()
                .map(str::trim)
        })
        .filter(|name| !name.is_empty())
}
use std::fmt::Write as _;
