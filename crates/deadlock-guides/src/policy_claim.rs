use std::collections::BTreeSet;

use deadlock_data::{Error, EvidenceUnit, Result};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum ClaimClass {
    Mechanical,
    Descriptive,
    Predictive,
    Causal,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EvidenceClaim {
    pub claim_id: String,
    pub claim_class: ClaimClass,
    pub snapshot_id: String,
    pub cohort: Map<String, Value>,
    pub unit: EvidenceUnit,
    pub support: u64,
    pub mechanics_refs: Vec<String>,
    pub language_ceiling: BTreeSet<String>,
    #[serde(default)]
    pub numerator: Option<u64>,
    #[serde(default)]
    pub denominator: Option<u64>,
    #[serde(default)]
    pub estimate: Option<f64>,
    #[serde(default)]
    pub interval: Option<[f64; 2]>,
    #[serde(default)]
    pub comparison_baseline: Option<f64>,
}

impl EvidenceClaim {
    /// # Errors
    /// Returns an error when claim identity, support, numerical values, or permitted language is invalid.
    pub fn validate(&self) -> Result<()> {
        if self.claim_id.trim().is_empty()
            || self.snapshot_id.trim().is_empty()
            || self.cohort.is_empty()
        {
            return Err(Error::new(
                "Evidence claim requires an identity, snapshot, and cohort",
            ));
        }
        let allowed: &[&str] = match self.claim_class {
            ClaimClass::Mechanical => &["grants", "scales", "requires", "can target"],
            ClaimClass::Descriptive => {
                &["observed", "associated", "adopted", "rate", "more common"]
            }
            ClaimClass::Predictive => &["predicts", "estimated", "conditional", "expected"],
            ClaimClass::Causal => &["causes", "improves", "reduces", "effect"],
        };
        if self
            .language_ceiling
            .iter()
            .any(|word| !allowed.contains(&word.as_str()))
        {
            return Err(Error::new("Evidence claim exceeds its permitted language"));
        }
        if self.claim_class == ClaimClass::Mechanical && self.mechanics_refs.is_empty() {
            return Err(Error::new("Mechanical claim has no mechanics references"));
        }
        if self.support == 0 && (self.estimate.is_some() || self.interval.is_some()) {
            return Err(Error::new("Quantitative claim has no support"));
        }
        let numbers = self
            .estimate
            .into_iter()
            .chain(self.comparison_baseline)
            .chain(self.interval.into_iter().flatten());
        if numbers.into_iter().any(|value| !value.is_finite())
            || self.interval.is_some_and(|[lower, upper]| lower > upper)
            || self
                .denominator
                .is_some_and(|denominator| denominator != self.support)
        {
            return Err(Error::new(
                "Evidence claim has invalid values, interval, or denominator",
            ));
        }
        Ok(())
    }

    /// # Errors
    /// Returns an error when noncausal evidence uses causal language.
    pub fn validate_sentence(&self, sentence: &str) -> Result<()> {
        let sentence = sentence.to_lowercase();
        if self.claim_class != ClaimClass::Causal
            && [
                "causes",
                "adds win rate",
                "improves win rate",
                "increases your chance",
                "item impact",
                "guarantees",
            ]
            .iter()
            .any(|phrase| sentence.contains(phrase))
        {
            return Err(Error::new(format!(
                "Sentence exceeds the evidence for claim {}",
                self.claim_id
            )));
        }
        Ok(())
    }
}
