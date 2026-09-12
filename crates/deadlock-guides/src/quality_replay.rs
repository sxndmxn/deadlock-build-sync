use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Error, Result, array, integer, text};
use serde_json::Value;

use crate::decision_state::DecisionState;
use crate::policy_artifact::PolicyArtifact;
use crate::policy_model::BuildPolicy;
use crate::recommendation_types::RecommendationAction;

#[derive(Debug)]
pub struct ReplayCase {
    pub policy_id: String,
    pub match_group: String,
    pub state: DecisionState,
    pub observed_action: RecommendationAction,
    pub observed_item_id: Option<u64>,
    pub core_completed: bool,
    pub behind: bool,
    pub ambiguous_purchase: bool,
}

/// # Errors
/// Returns an error when replay reuses training observations or contains incompatible, malformed, repeated, or future-derived decisions.
pub fn parse_replay(
    document: &Value,
    policies: &PolicyArtifact,
    cutoff: i64,
    evidence_id: &str,
) -> Result<Vec<ReplayCase>> {
    if document["schema_version"].as_u64() != Some(1)
        || document["cohort_selection"] != "all_eligible_player_matches"
    {
        return Err(Error::new(
            "Replay requires schema 1 and all eligible player matches",
        ));
    }
    let by_id = policies
        .policies()
        .values()
        .map(|policy| (policy.policy_id(), policy))
        .collect::<BTreeMap<_, _>>();
    let mut seen = BTreeSet::new();
    let mut cases = Vec::new();
    for row in array(&document["cases"])? {
        let id = text(row, "policy_id")?;
        let policy = by_id
            .get(id)
            .ok_or_else(|| Error::new("Replay references another frozen policy"))?;
        let case = parse_case(row, policy, cutoff)?;
        if case.state.content().build_evidence_id != evidence_id {
            return Err(Error::new("Replay references another evidence artifact"));
        }
        if !seen.insert((
            case.policy_id.clone(),
            case.match_group.clone(),
            case.state.content().hero_id,
            case.state.content().clock_s,
        )) {
            return Err(Error::new("Replay repeats a decision opportunity"));
        }
        cases.push(case);
    }
    Ok(cases)
}

fn parse_case(row: &Value, policy: &BuildPolicy, cutoff: i64) -> Result<ReplayCase> {
    let state = DecisionState::from_document(&row["state"])?;
    if state.content().hero_id != policy.content().hero_id {
        return Err(Error::new("Replay hero differs from the frozen policy"));
    }
    validate_timestamps(row, &state, cutoff)?;
    let group = text(row, "match_group")?;
    if group.trim().is_empty() {
        return Err(Error::new("Replay lacks a deidentified match group"));
    }
    let action: RecommendationAction = serde_json::from_value(row["observed_action"].clone())?;
    let item = row.get("observed_item_id").ok_or_else(|| {
        Error::new("Replay requires observed_item_id, with null for non-purchase actions")
    })?;
    let item =
        if action == RecommendationAction::Buy {
            Some(item.as_u64().filter(|id| *id > 0).ok_or_else(|| {
                Error::new("Observed purchase requires a positive item identifier")
            })?)
        } else if item.is_null() {
            None
        } else {
            return Err(Error::new("Only observed purchases can name an item"));
        };
    Ok(ReplayCase {
        policy_id: policy.policy_id().into(),
        match_group: group.into(),
        state,
        observed_action: action,
        observed_item_id: item,
        core_completed: boolean(row, "core_completed")?,
        behind: boolean(row, "behind")?,
        ambiguous_purchase: boolean(row, "ambiguous_purchase")?,
    })
}

fn validate_timestamps(row: &Value, state: &DecisionState, cutoff: i64) -> Result<()> {
    let start = integer(row, "match_start_timestamp")?;
    let observed = integer(row, "feature_as_of_timestamp")?;
    let assigned = integer(row, "policy_assigned_at")?;
    let cutoff = u64::try_from(cutoff)?;
    let decision_time = start
        .checked_add(state.content().clock_s)
        .ok_or_else(|| Error::new("Replay decision timestamp exceeds 64 bits"))?;
    if start <= cutoff
        || assigned <= cutoff
        || assigned > start
        || !(start..=decision_time).contains(&observed)
    {
        return Err(Error::new(
            "Replay timestamps violate the frozen cutoff, policy assignment, or decision window",
        ));
    }
    Ok(())
}

fn boolean(row: &Value, name: &str) -> Result<bool> {
    row[name]
        .as_bool()
        .ok_or_else(|| Error::new(format!("Replay requires boolean {name}")))
}
