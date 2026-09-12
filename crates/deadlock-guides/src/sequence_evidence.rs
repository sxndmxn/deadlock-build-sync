use std::collections::BTreeSet;

use deadlock_data::{Error, Result};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SequenceLevel {
    FirstPreviousPosition,
    PreviousPosition,
    Position,
    Popularity,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SequenceProduction {
    DeterministicBackoff,
    Pairwise,
    Beam16,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SequenceTransition {
    pub level: SequenceLevel,
    pub first_item_id: u64,
    pub previous_item_id: u64,
    pub position: u64,
    pub next_item_id: u64,
    pub support: u64,
    pub context_support: u64,
}

impl SequenceTransition {
    fn validate(&self, minimum_support: u64) -> Result<()> {
        if self.next_item_id == 0
            || self.support < minimum_support
            || self.context_support < self.support
        {
            return Err(Error::new(
                "Sequence policy has an invalid transition or insufficient support",
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SequencePolicyContent {
    pub version: u32,
    #[serde(rename = "component_expanded_default_path")]
    pub default_path: Vec<u64>,
    pub transitions: Vec<SequenceTransition>,
    pub minimum_support: u64,
    pub production_model: SequenceProduction,
    pub evaluation: Map<String, Value>,
}

#[derive(Clone, Debug)]
pub struct SequencePolicy(SequencePolicyContent);

impl SequencePolicy {
    /// # Errors
    /// Returns an error when the sequence policy has invalid paths, transitions, or support.
    pub fn from_document(value: &Value) -> Result<Self> {
        let content: SequencePolicyContent = serde_json::from_value(value.clone())?;
        if content.version != 3 || content.minimum_support < 20 {
            return Err(Error::new("Hero has no supported sequence policy"));
        }
        if content.default_path.is_empty() || content.default_path.contains(&0) {
            return Err(Error::new(
                "Sequence policy requires a nonempty path with positive item identifiers",
            ));
        }
        if content.production_model == SequenceProduction::DeterministicBackoff
            && (content.transitions.is_empty()
                || content.default_path.iter().collect::<BTreeSet<_>>().len()
                    != content.default_path.len())
        {
            return Err(Error::new(
                "Deterministic sequence requires transitions and a path without repeated items",
            ));
        }
        for transition in &content.transitions {
            transition.validate(content.minimum_support)?;
        }
        Ok(Self(content))
    }

    #[must_use]
    pub const fn content(&self) -> &SequencePolicyContent {
        &self.0
    }

    /// # Errors
    /// Returns an error when JSON serialization fails.
    pub fn to_document(&self) -> Result<Value> {
        Ok(serde_json::to_value(&self.0)?)
    }
}
