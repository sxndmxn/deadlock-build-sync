use std::collections::BTreeMap;

use deadlock_data::{Error, Result, array};
use deadlock_input::HeroDurationStat;
use serde_json::{Value, json};

use crate::ability_timeline::AbilityTimelineStep;
use crate::duration_profile::{DurationDistribution, summarize_ending_duration_profile};
use crate::purchase_guide::PurchaseGuide;

pub fn describe_ability_policy(
    guide: &PurchaseGuide,
    kit: &Value,
    timeline: &[AbilityTimelineStep],
) -> Result<Value> {
    let Some(path) = &guide.ability_path else {
        return Ok(Value::Null);
    };
    if timeline.len() != path.ability_ids.len() {
        return Ok(Value::Null);
    }
    if timeline.len() != path.decision_support.len() {
        return Err(Error::new("Ability policy has incomplete decision support"));
    }
    let names = array(&kit["abilities"])?
        .iter()
        .filter_map(|ability| {
            ability["id"]
                .as_u64()
                .map(|id| (id, ability["name"].as_str().unwrap_or_default()))
        })
        .collect::<BTreeMap<_, _>>();
    let mut purchases = BTreeMap::<u64, u32>::new();
    let mut steps = Vec::new();
    for (index, (id, scheduled)) in path.ability_ids.iter().zip(timeline).enumerate() {
        let prior = purchases.entry(*id).or_default();
        let name = names
            .get(id)
            .filter(|name| !name.is_empty())
            .map_or_else(|| id.to_string(), |name| (*name).to_owned());
        steps.push(json!({"position":index+1,"earliest_legal_level":scheduled.level,"ability_id":id,"ability":name,
            "action":if *prior==0 {"UNLOCK".into()} else {format!("UPGRADE_{prior}")}, "currency":scheduled.currency,
            "cost":scheduled.cost,"ability_points_remaining":scheduled.ap_remaining,"ability_unlocks_remaining":scheduled.unlocks_remaining,
            "decision_reached_support":path.decision_support[index]}));
        *prior += 1;
    }
    Ok(
        json!({"selection":path.selection,"filter_item_ids":path.filter_item_ids,"quality":path.quality_assessment(),
        "language_ceiling":"descriptive default projection, not a universal path","all_valid_telemetry_appearances":path.cohort_matches,
        "complete_path_appearances":path.complete_path_matches,"final_branch_support":path.matches,
        "observed_final_branch_outcome_rate":path.observed_final_branch_outcome_rate()?,"steps":steps}),
    )
}

pub fn ending_duration_evidence(
    points: &[HeroDurationStat],
    distribution: Option<&DurationDistribution>,
) -> Result<Value> {
    Ok(summarize_ending_duration_profile(points, distribution)?.unwrap_or_else(|| json!({
        "estimand":"ending_duration_profile","status":"abstained","strongest_phase":"UNAVAILABLE","weakest_phase":"UNAVAILABLE",
        "reason":"The frozen cohort lacks complete supported duration buckets; no phase-strength claim is available.",
        "buckets":points.iter().map(|point| json!({"label":point.label,"min_duration_s":point.min_duration_s,
            "max_duration_s":point.max_duration_s,"matches":point.matches})).collect::<Vec<_>>(),
    })))
}
