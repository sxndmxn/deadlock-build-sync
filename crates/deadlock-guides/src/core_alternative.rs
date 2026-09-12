use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Error, Result, object};
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::evidence_values::{close, finite, integer, nonnegative, probability};

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct CoreAlternativeContent {
    pub item_id: u64,
    pub comparator_item_id: u64,
    pub stage: usize,
    pub support: u64,
    pub comparison_support: u64,
    pub effective_support: f64,
    pub overlap: f64,
    pub stable: bool,
    pub dr_estimate: f64,
    pub comparative_interval: [f64; 2],
    pub vs: String,
    pub why: String,
    pub swap: String,
    pub when: String,
    pub skip: String,
    pub mechanics_refs: Vec<String>,
    pub comparator_mechanics_refs: Vec<String>,
    pub fold_estimates: BTreeMap<String, f64>,
    pub fold_diagnostics: BTreeMap<String, Value>,
}

#[derive(Clone, Debug)]
pub struct CoreAlternativeEvidence(CoreAlternativeContent);

impl CoreAlternativeEvidence {
    /// # Errors
    /// Returns an error when membership, mechanics references, support, or comparative evidence fails admission.
    pub fn from_document(
        value: &Value,
        item_ids: &BTreeSet<u64>,
        default_ids: &BTreeSet<u64>,
    ) -> Result<Self> {
        let mut content: CoreAlternativeContent = serde_json::from_value(value.clone())?;
        validate_identity(&content, item_ids, default_ids)?;
        normalize_text(&mut content)?;
        validate_support(&content)?;
        validate_positive_interval(content.comparative_interval, Some(content.dr_estimate))?;
        validate_folds(&mut content)?;
        Ok(Self(content))
    }

    #[must_use]
    pub const fn content(&self) -> &CoreAlternativeContent {
        &self.0
    }

    /// # Errors
    /// Returns an error when JSON serialization fails.
    pub fn to_document(&self) -> Result<Value> {
        Ok(serde_json::to_value(&self.0)?)
    }
}

fn validate_identity(
    content: &CoreAlternativeContent,
    items: &BTreeSet<u64>,
    default: &BTreeSet<u64>,
) -> Result<()> {
    if content.item_id == 0
        || content.comparator_item_id == 0
        || content.stage == 0
        || !items.contains(&content.item_id)
        || default.contains(&content.item_id)
        || !default.contains(&content.comparator_item_id)
    {
        return Err(Error::new(
            "Core alternative has an invalid item pair or purchase stage",
        ));
    }
    Ok(())
}

fn normalize_text(content: &mut CoreAlternativeContent) -> Result<()> {
    for text in [
        &mut content.vs,
        &mut content.why,
        &mut content.swap,
        &mut content.when,
        &mut content.skip,
    ] {
        *text = text.trim().into();
        if text.is_empty() {
            return Err(Error::new("Core alternative has an incomplete description"));
        }
    }
    for references in [
        &mut content.mechanics_refs,
        &mut content.comparator_mechanics_refs,
    ] {
        if references.is_empty() {
            return Err(Error::new("Core alternative has no mechanics references"));
        }
        for reference in references {
            *reference = reference.trim().into();
            if reference.is_empty() {
                return Err(Error::new(
                    "Core alternative has an empty mechanics reference",
                ));
            }
        }
    }
    Ok(())
}

fn validate_support(content: &CoreAlternativeContent) -> Result<()> {
    if content.support < 20
        || content.comparison_support < 20
        || !content.effective_support.is_finite()
        || content.effective_support < 20.0
        || !content.overlap.is_finite()
        || !(0.5..=1.0).contains(&content.overlap)
        || !content.stable
    {
        return Err(Error::new(
            "Core alternative lacks sufficient support, overlap, or stability",
        ));
    }
    Ok(())
}

pub fn validate_positive_interval([lower, upper]: [f64; 2], estimate: Option<f64>) -> Result<()> {
    if !lower.is_finite()
        || !upper.is_finite()
        || lower <= 0.0
        || lower > upper
        || upper - lower > 0.10
    {
        return Err(Error::new(
            "Comparative interval fails the positive effect or uncertainty requirement",
        ));
    }
    if estimate
        .is_some_and(|estimate| !estimate.is_finite() || estimate < lower || estimate > upper)
    {
        return Err(Error::new("Comparative estimate is outside its interval"));
    }
    Ok(())
}

fn validate_folds(content: &mut CoreAlternativeContent) -> Result<()> {
    if content
        .fold_estimates
        .values()
        .any(|value| !value.is_finite())
    {
        return Err(Error::new("Core alternative fold estimate must be finite"));
    }
    let mut selected = BTreeMap::new();
    let mut estimates = Vec::new();
    for fold in ["train", "validation"] {
        let estimate = *content
            .fold_estimates
            .get(fold)
            .ok_or_else(|| Error::new(format!("Core alternative lacks its {fold} estimate")))?;
        let diagnostics = content
            .fold_diagnostics
            .get(fold)
            .ok_or_else(|| Error::new(format!("Core alternative lacks {fold} diagnostics")))?;
        selected.insert(fold.into(), validate_diagnostics(diagnostics, estimate)?);
        estimates.push(estimate);
    }
    if (estimates[0] - estimates[1]).abs() > 0.05 {
        return Err(Error::new(
            "Core alternative has unstable temporal estimates",
        ));
    }
    content.fold_diagnostics = selected;
    Ok(())
}

fn validate_diagnostics(value: &Value, expected_estimate: f64) -> Result<Value> {
    let mut result = object(value)?.clone();
    let interval: [f64; 2] = serde_json::from_value(value["interval"].clone())?;
    let estimate = finite(&value["estimate"], "fold comparative estimate")?;
    validate_positive_interval(interval, Some(estimate))?;
    let support = integer(&value["support"], "fold alternative support", 20)?;
    let comparison_support = integer(&value["comparison_support"], "fold comparator support", 20)?;
    let effective = nonnegative(&value["effective_support"], "fold effective support")?;
    let overlap = probability(&value["overlap"], "fold overlap")?;
    let balance = nonnegative(
        &value["maximum_standardized_mean_difference"],
        "fold covariate imbalance",
    )?;
    if effective < 20.0
        || overlap < 0.5
        || balance > 0.1
        || !close(expected_estimate, estimate, 1.0e-12)
    {
        return Err(Error::new(
            "Core alternative fold fails support, overlap, balance, or estimate consistency",
        ));
    }
    result.extend([
        ("support".into(), support.into()),
        ("comparison_support".into(), comparison_support.into()),
        ("effective_support".into(), effective.into()),
        ("overlap".into(), overlap.into()),
        (
            "maximum_standardized_mean_difference".into(),
            balance.into(),
        ),
        ("estimate".into(), estimate.into()),
        ("interval".into(), serde_json::to_value(interval)?),
    ]);
    Ok(result.into())
}
