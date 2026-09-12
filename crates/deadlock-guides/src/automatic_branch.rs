use std::collections::BTreeSet;

use deadlock_data::{Error, Result, array, object};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

use crate::branch_diagnostics::validate_branch_diagnostics;
use crate::discovery_evidence::validate_discovery;
use crate::purchase_plan_types::PurchasePlan;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AutomaticCondition {
    RelativeWealth,
    EnemyHero,
    EnemyItem,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(untagged)]
pub enum BranchTrigger {
    Name(String),
    Identifier(u64),
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct AutomaticBranch {
    pub item_id: u64,
    pub after_step: usize,
    pub condition: AutomaticCondition,
    pub value: BranchTrigger,
    pub lower_bound: f64,
    pub support: u64,
    pub comparator_item_id: u64,
    pub evidence: Map<String, Value>,
    #[serde(default)]
    pub substituted_core: Vec<u64>,
    #[serde(default)]
    pub substituted_path: Vec<u64>,
    #[serde(default)]
    pub substitution_evidence: Map<String, Value>,
    #[serde(default)]
    pub default_plan: Option<PurchasePlan>,
}

/// # Errors
/// Returns an error when an automatic branch has invalid triggers, support, comparisons, or substitution evidence.
pub fn parse_automatic_branches(
    value: &Value,
    pool: &BTreeSet<u64>,
    path: &[u64],
) -> Result<Vec<AutomaticBranch>> {
    if value.is_null() {
        return Ok(Vec::new());
    }
    if value["version"].as_u64() != Some(1) {
        return Err(Error::new(
            "Automatic choice evidence has an invalid contract",
        ));
    }
    let mut identities = BTreeSet::new();
    let mut branches = Vec::new();
    for row in array(&value["branches"])? {
        let mut branch: AutomaticBranch = serde_json::from_value(row.clone())?;
        validate_branch(&branch, pool, path)?;
        let (core, route) = parse_substitution(
            &row["substitution"],
            path,
            branch.item_id,
            branch.after_step,
        )?;
        branch.substituted_core = core;
        branch.substituted_path = route;
        branch.substitution_evidence = row
            .get("substitution")
            .filter(|value| !value.is_null())
            .map(object)
            .transpose()?
            .cloned()
            .unwrap_or_default();
        branch.default_plan = None;
        let identity = (
            branch.item_id,
            branch.after_step,
            branch.condition,
            branch.value.clone(),
            branch.substituted_core.clone(),
        );
        if !identities.insert(identity) {
            return Err(Error::new(
                "Automatic choice evidence contains duplicate branches",
            ));
        }
        branches.push(branch);
    }
    Ok(branches)
}

fn validate_branch(branch: &AutomaticBranch, pool: &BTreeSet<u64>, path: &[u64]) -> Result<()> {
    if !pool.contains(&branch.item_id)
        || path.get(branch.after_step) != Some(&branch.comparator_item_id)
        || branch.support < 40
        || !branch.lower_bound.is_finite()
        || branch.lower_bound <= 0.0
        || branch.lower_bound > 1.0
    {
        return Err(Error::new(
            "Automatic choice identity or support is invalid",
        ));
    }
    validate_condition(branch.condition, &branch.value)?;
    let evidence = Value::Object(branch.evidence.clone());
    validate_gates(&evidence)?;
    if evidence["test_evaluated"].as_bool() != Some(false)
        || evidence["lower_bound"].as_f64() != Some(branch.lower_bound)
    {
        return Err(Error::new(
            "Automatic choice has incompatible outcome evidence",
        ));
    }
    validate_branch_diagnostics(&evidence, branch.support, branch.lower_bound)
}

fn validate_gates(evidence: &Value) -> Result<()> {
    let expected = [
        "support",
        "overlap",
        "balance",
        "uncertainty",
        "temporal_stability",
        "corrected_outcome",
        "legal_path",
        "pre_decision_cohort",
    ];
    let gates = object(&evidence["gates"])?;
    if gates.len() != expected.len()
        || expected
            .iter()
            .any(|key| gates.get(*key).and_then(Value::as_bool) != Some(true))
    {
        return Err(Error::new(
            "Automatic choice did not pass all admission requirements",
        ));
    }
    Ok(())
}

fn validate_condition(condition: AutomaticCondition, trigger: &BranchTrigger) -> Result<()> {
    let valid = match (condition, trigger) {
        (AutomaticCondition::RelativeWealth, BranchTrigger::Name(name)) => {
            ["behind", "even", "ahead"].contains(&name.as_str())
        }
        (
            AutomaticCondition::EnemyHero | AutomaticCondition::EnemyItem,
            BranchTrigger::Identifier(id),
        ) => *id > 0,
        _ => false,
    };
    if !valid {
        return Err(Error::new("Automatic choice trigger is invalid"));
    }
    Ok(())
}

fn parse_substitution(
    value: &Value,
    path: &[u64],
    item: u64,
    checkpoint: usize,
) -> Result<(Vec<u64>, Vec<u64>)> {
    if value.is_null() {
        return Ok((Vec::new(), Vec::new()));
    }
    object(value)?;
    let core: Vec<u64> = serde_json::from_value(value["core"].clone())?;
    let route: Vec<u64> = serde_json::from_value(value["path"].clone())?;
    let discovery = &value["discovery"];
    object(discovery)?;
    let mut expected = path.to_vec();
    let target = expected
        .get_mut(checkpoint)
        .ok_or_else(|| Error::new("Substitution checkpoint is outside the purchase path"))?;
    *target = item;
    if core.contains(&0)
        || route.contains(&0)
        || route != expected
        || !core.contains(&item)
        || value["source_identity_id"] != discovery["identity_id"]
    {
        return Err(Error::new(
            "Core substitution differs from its admitted purchase path",
        ));
    }
    validate_discovery(discovery, &core, &route)?;
    if discovery["evidence_status"].as_str() != Some("outcome_supported") {
        return Err(Error::new(
            "Core substitution lacks supported outcome evidence",
        ));
    }
    Ok((core, route))
}
