use std::collections::BTreeMap;

use deadlock_data::{Error, Result};
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::core_alternative::validate_positive_interval;
use crate::threat::{EnemyScope, Threat};

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SituationalBranchContent {
    pub threat: Threat,
    pub item_id: u64,
    pub enemy_hero_id: Option<u64>,
    pub enemy_scope: EnemyScope,
    pub phase: u8,
    pub tier: u8,
    pub mechanic_ref: String,
    pub enemy_mechanics_refs: Vec<String>,
    pub comparator: String,
    pub comparator_item_id: u64,
    pub comparison_support: u64,
    pub same_opportunity: bool,
    pub support: u64,
    pub effective_support: f64,
    pub overlap: f64,
    pub stable: bool,
    pub comparative_interval: [f64; 2],
    pub fold_comparative_estimates: BTreeMap<String, f64>,
    pub fold_support: BTreeMap<String, BTreeMap<String, u64>>,
    pub trigger: String,
    pub replacement: String,
    pub execution: String,
    pub failure_condition: String,
}

#[derive(Clone, Debug)]
pub struct SituationalBranch(SituationalBranchContent);

impl SituationalBranch {
    /// # Errors
    /// Returns an error when a situational branch lacks compatible references or supported comparative evidence.
    pub fn from_document(value: &Value) -> Result<Self> {
        let mut content: SituationalBranchContent = serde_json::from_value(value.clone())?;
        validate_identity(&content)?;
        validate_text(&content)?;
        for reference in &mut content.enemy_mechanics_refs {
            *reference = reference.trim().into();
        }
        validate_support(&content)?;
        validate_positive_interval(content.comparative_interval, None)?;
        validate_folds(&mut content)?;
        Ok(Self(content))
    }

    #[must_use]
    pub const fn content(&self) -> &SituationalBranchContent {
        &self.0
    }

    /// # Errors
    /// Returns an error when JSON serialization fails.
    pub fn to_document(&self) -> Result<Value> {
        Ok(serde_json::to_value(&self.0)?)
    }
}

fn validate_identity(branch: &SituationalBranchContent) -> Result<()> {
    if branch.item_id == 0
        || branch.comparator_item_id == 0
        || branch.enemy_hero_id == Some(0)
        || branch.item_id == branch.comparator_item_id
        || branch.phase > 3
        || !(1..=4).contains(&branch.tier)
    {
        return Err(Error::new(
            "Situational branch has invalid item, enemy, phase, or tier fields",
        ));
    }
    if !branch
        .mechanic_ref
        .starts_with(&format!("item/{}/", branch.item_id))
    {
        return Err(Error::new(
            "Situational mechanic reference identifies a different item",
        ));
    }
    Ok(())
}

fn validate_text(branch: &SituationalBranchContent) -> Result<()> {
    if [
        &branch.mechanic_ref,
        &branch.comparator,
        &branch.trigger,
        &branch.replacement,
        &branch.execution,
        &branch.failure_condition,
    ]
    .iter()
    .any(|text| text.trim().is_empty())
    {
        return Err(Error::new(
            "Situational branch has an incomplete description",
        ));
    }
    if branch.enemy_mechanics_refs.is_empty()
        || branch
            .enemy_mechanics_refs
            .iter()
            .any(|reference| reference.trim().is_empty())
    {
        return Err(Error::new(
            "Situational branch lacks enemy mechanics references",
        ));
    }
    Ok(())
}

fn validate_support(branch: &SituationalBranchContent) -> Result<()> {
    if branch.support < 20
        || branch.comparison_support < 20
        || !branch.same_opportunity
        || !branch.stable
        || !branch.effective_support.is_finite()
        || branch.effective_support < 20.0
        || !branch.overlap.is_finite()
        || !(0.5..=1.0).contains(&branch.overlap)
    {
        return Err(Error::new(
            "Situational branch fails support, overlap, stability, or comparable opportunity requirements",
        ));
    }
    Ok(())
}

fn validate_folds(branch: &mut SituationalBranchContent) -> Result<()> {
    if branch
        .fold_comparative_estimates
        .values()
        .any(|estimate| !estimate.is_finite())
    {
        return Err(Error::new("Situational fold estimate must be finite"));
    }
    let mut estimates = Vec::new();
    let mut selected_support = BTreeMap::new();
    for fold in ["train", "validation", "test"] {
        let estimate = branch
            .fold_comparative_estimates
            .get(fold)
            .copied()
            .filter(|value| *value > 0.0)
            .ok_or_else(|| {
                Error::new(format!(
                    "Situational branch lacks a positive {fold} estimate"
                ))
            })?;
        let support = branch
            .fold_support
            .get(fold)
            .ok_or_else(|| Error::new(format!("Situational branch lacks {fold} support")))?;
        let mut selected = BTreeMap::new();
        for side in ["item", "comparator"] {
            let count = support
                .get(side)
                .copied()
                .filter(|count| *count >= 20)
                .ok_or_else(|| {
                    Error::new(format!(
                        "Situational branch has insufficient {fold} {side} support"
                    ))
                })?;
            selected.insert(side.into(), count);
        }
        selected_support.insert(fold.into(), selected);
        estimates.push(estimate);
    }
    if (estimates[0] - estimates[1]).abs() > 0.05 {
        return Err(Error::new(
            "Situational branch has unstable temporal estimates",
        ));
    }
    branch.fold_support = selected_support;
    Ok(())
}
