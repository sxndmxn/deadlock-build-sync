use std::collections::BTreeMap;
use std::ops::Bound::{Excluded, Included};

use deadlock_data::{Error, Result};
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::ability_definition::AbilityDefinition;
use crate::ability_grants::{AbilityGrants, parse_ability_grants};

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct AbilityAction {
    pub level: u32,
    pub ability_id: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AbilityCurrency {
    AbilityUnlock,
    AbilityPoints,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct AbilityTimelineStep {
    pub level: u32,
    pub ability_id: u64,
    pub rank: usize,
    pub cost: u32,
    pub currency: AbilityCurrency,
    pub ap_remaining: u32,
    pub unlocks_remaining: u32,
}

#[derive(Clone, Debug, Default)]
struct AbilityProgress {
    ranks: BTreeMap<u64, usize>,
    points: u32,
    unlocks: u32,
    current_level: u32,
}

impl AbilityProgress {
    fn advance_level(&mut self, grants: &AbilityGrants, level: u32) -> Result<()> {
        for grant in grants
            .range((Excluded(self.current_level), Included(level)))
            .map(|(_, grant)| grant)
        {
            self.unlocks = self
                .unlocks
                .checked_add(grant.unlocks)
                .ok_or_else(|| Error::new("Ability unlock balance exceeds 32 bits"))?;
            self.points = self
                .points
                .checked_add(grant.points)
                .ok_or_else(|| Error::new("Ability point balance exceeds 32 bits"))?;
        }
        self.current_level = level;
        Ok(())
    }

    fn apply(
        &mut self,
        definitions: &BTreeMap<u64, AbilityDefinition>,
        action: AbilityAction,
    ) -> Result<AbilityTimelineStep> {
        let definition = definitions
            .get(&action.ability_id)
            .ok_or_else(|| Error::new(format!("Unknown ability: {}", action.ability_id)))?;
        let prior_rank = self.ranks.get(&action.ability_id).copied().unwrap_or(0);
        let (cost, currency) = if prior_rank == 0 {
            self.unlock(definition, action.level)?;
            (1, AbilityCurrency::AbilityUnlock)
        } else {
            (
                self.upgrade(definition, prior_rank)?,
                AbilityCurrency::AbilityPoints,
            )
        };
        let rank = prior_rank + 1;
        self.ranks.insert(action.ability_id, rank);
        Ok(AbilityTimelineStep {
            level: action.level,
            ability_id: action.ability_id,
            rank,
            cost,
            currency,
            ap_remaining: self.points,
            unlocks_remaining: self.unlocks,
        })
    }

    fn unlock(&mut self, definition: &AbilityDefinition, level: u32) -> Result<()> {
        if level < definition.unlock_level {
            return Err(Error::new(format!(
                "Ability {} requires level {}",
                definition.ability_id, definition.unlock_level
            )));
        }
        self.unlocks = self.unlocks.checked_sub(1).ok_or_else(|| {
            Error::new(format!(
                "Ability {} requires one unlock token",
                definition.ability_id
            ))
        })?;
        Ok(())
    }

    fn upgrade(&mut self, definition: &AbilityDefinition, prior_rank: usize) -> Result<u32> {
        let cost = *definition
            .upgrade_costs
            .get(prior_rank - 1)
            .ok_or_else(|| {
                Error::new(format!(
                    "Ability {} is at its maximum rank",
                    definition.ability_id
                ))
            })?;
        self.points = self.points.checked_sub(cost).ok_or_else(|| {
            Error::new(format!(
                "Ability {} requires {cost} points; {} are available",
                definition.ability_id, self.points
            ))
        })?;
        Ok(cost)
    }
}

/// # Errors
/// Returns an error when the sequence violates level, currency, or ability limits.
pub fn validate_ability_timeline(
    definitions: &BTreeMap<u64, AbilityDefinition>,
    level_info: &Value,
    actions: &[AbilityAction],
) -> Result<Vec<AbilityTimelineStep>> {
    validate_definitions(definitions)?;
    let grants = parse_ability_grants(level_info)?;
    if actions.windows(2).any(|pair| pair[0].level > pair[1].level) {
        return Err(Error::new("Ability actions must be in level order"));
    }
    let mut progress = AbilityProgress::default();
    actions
        .iter()
        .map(|action| {
            if !grants.contains_key(&action.level) {
                return Err(Error::new(format!(
                    "Ability action uses an unknown level: {}",
                    action.level
                )));
            }
            progress.advance_level(&grants, action.level)?;
            progress.apply(definitions, *action)
        })
        .collect()
}

/// Schedules observed ability purchases at their earliest legal levels.
///
/// # Errors
/// Returns an error when the level grants cannot realize the sequence.
pub fn schedule_ability_path(
    definitions: &BTreeMap<u64, AbilityDefinition>,
    level_info: &Value,
    ability_ids: &[u64],
) -> Result<Vec<AbilityAction>> {
    validate_definitions(definitions)?;
    let grants = parse_ability_grants(level_info)?;
    let mut progress = AbilityProgress::default();
    let mut actions = Vec::with_capacity(ability_ids.len());
    for id in ability_ids {
        let action = schedule_one(definitions, &grants, &mut progress, *id)?;
        actions.push(action);
    }
    Ok(actions)
}

fn schedule_one(
    definitions: &BTreeMap<u64, AbilityDefinition>,
    grants: &AbilityGrants,
    progress: &mut AbilityProgress,
    ability_id: u64,
) -> Result<AbilityAction> {
    for level in grants
        .range(progress.current_level..)
        .map(|(level, _)| *level)
    {
        let mut candidate = progress.clone();
        candidate.advance_level(grants, level)?;
        let action = AbilityAction { level, ability_id };
        if candidate.apply(definitions, action).is_ok() {
            *progress = candidate;
            return Ok(action);
        }
    }
    Err(Error::new(format!(
        "Ability path cannot legally schedule ability {ability_id}"
    )))
}

fn validate_definitions(definitions: &BTreeMap<u64, AbilityDefinition>) -> Result<()> {
    for (id, definition) in definitions {
        if *id == 0
            || *id != definition.ability_id
            || definition.unlock_level == 0
            || definition.upgrade_costs.contains(&0)
        {
            return Err(Error::new(
                "Ability definition has an invalid identifier, unlock level, or upgrade cost",
            ));
        }
    }
    Ok(())
}
