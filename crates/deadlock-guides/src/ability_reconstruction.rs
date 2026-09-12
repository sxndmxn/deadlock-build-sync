use std::collections::BTreeMap;

use deadlock_data::{Error, Result, array, count_from_probability, integer, real};
use serde_json::Value;

use crate::ability_path::AbilityPath;
use crate::policy_model::BuildPolicy;
use crate::policy_node::NodeKind;

pub fn reconstruct_ability_path(hero: &Value, policy: &BuildPolicy) -> Result<AbilityPath> {
    let raw = &hero["ability_policy"];
    let (ability_ids, decision_support) = parse_ability_projection(raw, policy)?;
    let cohort = integer(raw, "all_valid_telemetry_appearances")?;
    let complete = integer(raw, "complete_path_appearances")?;
    let matches = integer(raw, "final_branch_support")?;
    if matches == 0 || matches > complete || complete > cohort {
        return Err(Error::new("Ability policy has inconsistent support"));
    }
    let wins = count_from_probability(real(raw, "observed_final_branch_outcome_rate")?, matches)?;
    let filter_item_ids = raw
        .get("filter_item_ids")
        .map(|value| serde_json::from_value(value.clone()))
        .transpose()?
        .unwrap_or_default();
    let path = AbilityPath {
        ability_ids,
        matches,
        wins,
        losses: matches - wins,
        cohort_matches: cohort,
        complete_path_matches: complete,
        decision_support,
        selection: raw["selection"]
            .as_str()
            .filter(|value| !value.is_empty())
            .unwrap_or("MOST_SUPPORTED_LEGAL_STATE")
            .into(),
        filter_item_ids,
        fallback_reason: raw["quality"]["fallback_reason"]
            .as_str()
            .map(str::to_owned),
    };
    if raw["quality"] != path.quality_assessment() {
        return Err(Error::new(
            "Ability quality assessment differs from its evidence",
        ));
    }
    Ok(path)
}

fn parse_ability_projection(raw: &Value, policy: &BuildPolicy) -> Result<(Vec<u64>, Vec<u64>)> {
    let steps = array(&raw["steps"])?;
    if steps.len() != 16 {
        return Err(Error::new("Ability policy must contain 16 actions"));
    }
    let mut ids = Vec::new();
    let mut support = Vec::new();
    let mut counts = BTreeMap::<u64, usize>::new();
    for step in steps {
        let id = integer(step, "ability_id")?;
        let count = integer(step, "decision_reached_support")?;
        if id == 0 || count == 0 {
            return Err(Error::new(
                "Ability action requires positive identity and support",
            ));
        }
        ids.push(id);
        support.push(count);
        *counts.entry(id).or_default() += 1;
    }
    if counts.len() != 4 || counts.values().any(|count| *count != 4) {
        return Err(Error::new(
            "Ability policy is not a complete four-rank path",
        ));
    }
    let expected = policy
        .content()
        .ability_plan
        .iter()
        .filter(|node| node.kind == NodeKind::Ability)
        .filter_map(|node| node.ability_id);
    if !ids.iter().copied().eq(expected) {
        return Err(Error::new("Ability projection differs from its policy"));
    }
    Ok((ids, support))
}
