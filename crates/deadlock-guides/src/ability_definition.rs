use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Error, Result, array, canonical_json, integer};
use serde::{Deserialize, Serialize};
use serde_json::Value;

pub const DEFAULT_ABILITY_UPGRADE_COSTS: [u32; 3] = [1, 2, 5];

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct AbilityDefinition {
    pub ability_id: u64,
    pub unlock_level: u32,
    pub upgrade_costs: Vec<u32>,
    pub qualifiers: BTreeSet<String>,
    pub ultimate: bool,
}

/// # Errors
/// Returns an error when the kit does not contain four distinct signature abilities.
pub fn parse_ability_definitions(kit: &Value) -> Result<BTreeMap<u64, AbilityDefinition>> {
    let abilities = array(&kit["abilities"])?;
    if abilities.len() != 4 {
        return Err(Error::new("Kit must contain four signature abilities"));
    }
    let mut result = BTreeMap::new();
    for ability in abilities {
        let id = integer(ability, "id")?;
        let definition = parse_definition(ability, id)?;
        if id == 0 || result.insert(id, definition).is_some() {
            return Err(Error::new(
                "Signature ability identifiers must be positive and distinct",
            ));
        }
    }
    Ok(result)
}

fn parse_definition(ability: &Value, id: u64) -> Result<AbilityDefinition> {
    let text = String::from_utf8(canonical_json(ability)?)
        .map_err(|error| Error::new(error.to_string()))?
        .to_lowercase();
    let mut qualifiers = ["charged", "channeled", "airborne"]
        .into_iter()
        .filter(|word| text.contains(word))
        .map(str::to_owned)
        .collect::<BTreeSet<_>>();
    if numeric_property(ability, "AbilityChannelTime").is_some_and(|value| value > 0.0) {
        qualifiers.insert("channeled".into());
    }
    let unlock_level = ability["unlock_level"]
        .as_u64()
        .filter(|level| *level > 0)
        .map_or(Ok(1), u32::try_from)?;
    let upgrade_costs = parse_upgrade_costs(&ability["upgrade_costs"])?;
    Ok(AbilityDefinition {
        ability_id: id,
        unlock_level,
        upgrade_costs,
        qualifiers,
        ultimate: ability["slot"].as_u64() == Some(4),
    })
}

fn parse_upgrade_costs(value: &Value) -> Result<Vec<u32>> {
    let Some(costs) = value.as_array().filter(|costs| {
        !costs.is_empty()
            && costs
                .iter()
                .all(|cost| cost.as_u64().is_some_and(|cost| cost > 0))
    }) else {
        return Ok(DEFAULT_ABILITY_UPGRADE_COSTS.to_vec());
    };
    costs
        .iter()
        .map(|cost| {
            let cost = cost
                .as_u64()
                .ok_or_else(|| Error::new("Ability upgrade cost must be a positive integer"))?;
            Ok(u32::try_from(cost)?)
        })
        .collect()
}

fn numeric_property(ability: &Value, name: &str) -> Option<f64> {
    let value = &ability["properties"][name]["value"];
    value
        .as_f64()
        .or_else(|| value.as_str()?.parse().ok())
        .filter(|number| number.is_finite())
}

/// # Errors
/// Returns an error when the imbue target is unknown, unlearned, or incompatible with an item restriction.
pub fn validate_imbue(
    definitions: &BTreeMap<u64, AbilityDefinition>,
    learned: &BTreeSet<u64>,
    ability_id: u64,
    required_qualifier: Option<&str>,
    allow_ultimate: bool,
) -> Result<()> {
    let definition = definitions
        .get(&ability_id)
        .filter(|_| learned.contains(&ability_id))
        .ok_or_else(|| Error::new("Imbue target must be a current learned ability"))?;
    if definition.ultimate && !allow_ultimate {
        return Err(Error::new("This item cannot imbue an ultimate ability"));
    }
    if let Some(qualifier) = required_qualifier.filter(|qualifier| !qualifier.is_empty())
        && !definition.qualifiers.contains(qualifier)
    {
        return Err(Error::new(format!(
            "Ability {ability_id} lacks the required qualifier: {qualifier}"
        )));
    }
    Ok(())
}
