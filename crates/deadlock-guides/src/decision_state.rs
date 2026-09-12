use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;

use deadlock_data::{Error, Result, count_as_f64, object, read_json};
use serde::{Deserialize, Serialize};
use serde_json::Value;

pub const DECISION_STATE_SCHEMA_VERSION: u8 = 3;

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct MatchEconomy {
    pub personal_net_worth: Option<u64>,
    #[serde(default)]
    pub lobby_net_worths: Vec<u64>,
    pub observed_at_s: Option<u64>,
}

impl MatchEconomy {
    /// # Errors
    /// Returns an error when combined lobby wealth exceeds the numeric range.
    pub fn relative_wealth(&self, clock_s: u64) -> Result<Option<f64>> {
        let Some(personal) = self.personal_net_worth else {
            return Ok(None);
        };
        if self.lobby_net_worths.len() != 12 || !recent_observation(clock_s, self.observed_at_s) {
            return Ok(None);
        }
        let total = self.lobby_net_worths.iter().try_fold(0_u64, |sum, value| {
            sum.checked_add(*value)
                .ok_or_else(|| Error::new("Lobby wealth exceeds 64 bits"))
        })?;
        if total == 0 {
            return Ok(None);
        }
        Ok(Some(count_as_f64(personal)? * 12.0 / count_as_f64(total)?))
    }
}

pub fn recent_observation(clock_s: u64, observed: Option<u64>) -> bool {
    observed
        .and_then(|observed| clock_s.checked_sub(observed))
        .is_some_and(|age| (1..=300).contains(&age))
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DecisionInventory {
    pub items: Vec<u64>,
    pub components: Vec<u64>,
    pub open_slots: usize,
    pub flex_slots: u8,
    pub active_bindings: usize,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DecisionStateContent {
    pub schema_version: u8,
    pub build_evidence_id: String,
    pub client_version: u64,
    pub patch_identity: String,
    pub match_mode: String,
    pub game_mode: String,
    pub hero_id: u64,
    pub clock_s: u64,
    pub average_badge: u64,
    pub liquid_souls: u64,
    pub purchases: Vec<u64>,
    pub inventory: DecisionInventory,
    pub learned_abilities: Vec<u64>,
    #[serde(default)]
    pub enemy_hero_ids: Vec<u64>,
    pub lane_enemy_hero_ids: Vec<u64>,
    #[serde(default)]
    pub enemy_item_ids: Vec<u64>,
    #[serde(default)]
    pub allied_hero_ids: Vec<u64>,
    #[serde(default)]
    pub objectives: Vec<String>,
    #[serde(default)]
    pub threats: Vec<String>,
    pub path_id: Option<String>,
    #[serde(default)]
    pub selected_optional_items: Vec<u64>,
    #[serde(default)]
    pub placement_overrides: BTreeMap<u64, usize>,
    pub core_substitution_item_id: Option<u64>,
    pub economy: Option<MatchEconomy>,
    pub enemy_observed_at_s: Option<u64>,
}

#[derive(Clone, Debug)]
pub struct DecisionState(DecisionStateContent);

impl DecisionState {
    /// # Errors
    /// Returns an error when state fields have unknown names, invalid types, repeated identifiers, or inconsistent team and choice references.
    pub fn from_document(document: &Value) -> Result<Self> {
        if let Some(placements) = document.get("placement_overrides") {
            for key in object(placements)?.keys() {
                if key
                    .parse::<u64>()
                    .ok()
                    .is_none_or(|id| id == 0 || id.to_string() != *key)
                {
                    return Err(Error::new(
                        "Placement override keys must be canonical positive item identifiers",
                    ));
                }
            }
        }
        let mut content: DecisionStateContent = serde_json::from_value(document.clone())?;
        validate_identity(&mut content)?;
        validate_collections(&mut content)?;
        if !content
            .placement_overrides
            .keys()
            .all(|id| content.selected_optional_items.contains(id))
            || !content
                .lane_enemy_hero_ids
                .iter()
                .all(|id| content.enemy_hero_ids.contains(id))
        {
            return Err(Error::new(
                "Decision state has inconsistent optional item or lane enemy references",
            ));
        }
        if content.core_substitution_item_id == Some(0)
            || content
                .economy
                .as_ref()
                .is_some_and(|economy| economy.lobby_net_worths.len() > 12)
        {
            return Err(Error::new(
                "Decision state has an invalid core substitution or lobby population",
            ));
        }
        Ok(Self(content))
    }

    /// # Errors
    /// Returns an error when the state file cannot be read or fails validation.
    pub fn load(path: &Path) -> Result<Self> {
        Self::from_document(&read_json(path)?)
    }

    #[must_use]
    pub const fn content(&self) -> &DecisionStateContent {
        &self.0
    }
}

fn validate_identity(state: &mut DecisionStateContent) -> Result<()> {
    if state.schema_version != DECISION_STATE_SCHEMA_VERSION
        || state.hero_id == 0
        || state.client_version == 0
        || state.average_badge == 0
    {
        return Err(Error::new(
            "Decision state has an invalid schema or numeric identity",
        ));
    }
    for text in [
        &mut state.build_evidence_id,
        &mut state.patch_identity,
        &mut state.match_mode,
        &mut state.game_mode,
    ]
    .into_iter()
    .chain(state.path_id.iter_mut())
    {
        *text = text.trim().into();
        if text.is_empty() {
            return Err(Error::new(
                "Decision state identity fields must not be empty",
            ));
        }
    }
    Ok(())
}

fn validate_collections(state: &mut DecisionStateContent) -> Result<()> {
    for ids in [
        &state.inventory.items,
        &state.inventory.components,
        &state.learned_abilities,
        &state.enemy_hero_ids,
        &state.lane_enemy_hero_ids,
        &state.enemy_item_ids,
        &state.allied_hero_ids,
        &state.selected_optional_items,
    ] {
        if ids.contains(&0) || ids.iter().collect::<BTreeSet<_>>().len() != ids.len() {
            return Err(Error::new(
                "Decision state identifiers must be positive and unique",
            ));
        }
    }
    if state.purchases.contains(&0) {
        return Err(Error::new("Purchase history identifiers must be positive"));
    }
    for values in [&mut state.objectives, &mut state.threats] {
        for value in values.iter_mut() {
            *value = value.trim().into();
        }
        if values.iter().any(String::is_empty)
            || values.iter().collect::<BTreeSet<_>>().len() != values.len()
        {
            return Err(Error::new(
                "Decision state labels must be nonempty and unique",
            ));
        }
    }
    Ok(())
}
