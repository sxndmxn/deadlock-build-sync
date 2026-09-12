use std::collections::BTreeMap;

use deadlock_data::{Error, Result};
use serde::{Deserialize, Serialize};

use crate::core_alternative::validate_positive_interval;
use crate::policy_claim::ClaimClass;

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CounterCard {
    pub threat: String,
    pub item_id: u64,
    pub comparator_item_id: u64,
    pub mechanic_ref: String,
    pub legal_timing: String,
    pub alternative: String,
    pub replacement: String,
    pub execution_mode: String,
    pub failure_condition: String,
    pub evidence_ref: String,
    #[serde(default)]
    pub enemy_hero_id: Option<u64>,
    #[serde(default = "enemy_scope")]
    pub enemy_scope: String,
    #[serde(default)]
    pub phase: u8,
    #[serde(default = "first_tier")]
    pub tier: u8,
    #[serde(default)]
    pub enemy_mechanics_refs: Vec<String>,
}

fn enemy_scope() -> String {
    "whole_enemy_team".into()
}
const fn first_tier() -> u8 {
    1
}

impl CounterCard {
    /// # Errors
    /// Returns an error when the counter card lacks mechanics, item identity, enemy state, or execution details.
    pub fn validate(&self) -> Result<()> {
        let text = [
            &self.threat,
            &self.mechanic_ref,
            &self.legal_timing,
            &self.alternative,
            &self.replacement,
            &self.execution_mode,
            &self.failure_condition,
            &self.evidence_ref,
        ];
        if self.item_id == 0
            || self.comparator_item_id == 0
            || self.item_id == self.comparator_item_id
            || text.iter().any(|value| value.trim().is_empty())
        {
            return Err(Error::new(
                "Counter card lacks a required mechanics or decision field",
            ));
        }
        if self.enemy_hero_id == Some(0)
            || !["same_lane", "whole_enemy_team"].contains(&self.enemy_scope.as_str())
            || self.phase > 3
            || !(1..=4).contains(&self.tier)
            || self.enemy_mechanics_refs.is_empty()
        {
            return Err(Error::new("Counter card has invalid enemy state evidence"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CoreAlternativeCard {
    pub vs: String,
    pub why: String,
    pub swap: String,
    pub when: String,
    pub skip: String,
    pub mechanics_refs: Vec<String>,
    pub comparator_mechanics_refs: Vec<String>,
    pub item_id: u64,
    pub comparator_item_id: u64,
    pub stage: u8,
    pub evidence_ref: String,
    pub support: u64,
    pub effective_support: f64,
    pub overlap: f64,
    pub interval: [f64; 2],
    pub fold_estimates: BTreeMap<String, f64>,
}

impl CoreAlternativeCard {
    /// # Errors
    /// Returns an error when the replacement identity, mechanics, support, interval, or temporal estimates fail admission.
    pub fn validate(&self) -> Result<()> {
        if self.item_id == 0
            || self.comparator_item_id == 0
            || self.item_id == self.comparator_item_id
            || !(1..=9).contains(&self.stage)
        {
            return Err(Error::new(
                "Core alternative card has an invalid replacement or stage",
            ));
        }
        if self.support < 20
            || !self.effective_support.is_finite()
            || self.effective_support < 20.0
            || !(0.5..=1.0).contains(&self.overlap)
        {
            return Err(Error::new(
                "Core alternative card has insufficient support or overlap",
            ));
        }
        validate_positive_interval(self.interval, None)?;
        if [
            &self.vs,
            &self.why,
            &self.swap,
            &self.when,
            &self.skip,
            &self.evidence_ref,
        ]
        .iter()
        .any(|text| text.trim().is_empty())
            || self.mechanics_refs.is_empty()
            || self.comparator_mechanics_refs.is_empty()
        {
            return Err(Error::new(
                "Core alternative card has incomplete text or mechanics references",
            ));
        }
        let train = self.fold_estimates.get("train");
        let validation = self.fold_estimates.get("validation");
        if self
            .fold_estimates
            .values()
            .any(|estimate| !estimate.is_finite())
            || train
                .zip(validation)
                .is_none_or(|(train, validation)| (train - validation).abs() > 0.05)
        {
            return Err(Error::new(
                "Core alternative card lacks consistent temporal estimates",
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SpikeCard {
    pub name: String,
    pub prerequisites: Vec<String>,
    pub acquisition_state: String,
    pub mechanical_delta: String,
    pub conversion_window: String,
    pub failure_conditions: Vec<String>,
    pub counterplay: Vec<String>,
    pub evidence_class: ClaimClass,
    pub confidence: f64,
    pub evidence_ref: String,
}

impl SpikeCard {
    /// # Errors
    /// Returns an error when the card lacks a supported mechanical transition, execution window, or confidence value.
    pub fn validate(&self) -> Result<()> {
        if !(0.0..=1.0).contains(&self.confidence) {
            return Err(Error::new("Spike confidence must be between zero and one"));
        }
        let text = [
            &self.name,
            &self.acquisition_state,
            &self.mechanical_delta,
            &self.conversion_window,
            &self.evidence_ref,
        ];
        if text.iter().any(|value| value.trim().is_empty())
            || self.prerequisites.is_empty()
            || self.failure_conditions.is_empty()
            || self.counterplay.is_empty()
        {
            return Err(Error::new(
                "Spike card lacks a required state transition field",
            ));
        }
        Ok(())
    }
}
