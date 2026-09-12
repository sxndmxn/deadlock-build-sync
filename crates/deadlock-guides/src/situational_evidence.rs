use std::collections::BTreeSet;

use deadlock_data::{Error, Result, array};
use serde_json::Value;

use crate::situational_branch::SituationalBranch;
use crate::threat::THREAT_CLASSES;

#[derive(Clone, Debug)]
pub struct SituationalPolicy {
    branches: Vec<SituationalBranch>,
    abstentions: Vec<String>,
}

impl SituationalPolicy {
    /// # Errors
    /// Returns an error when situational evidence is incomplete, repeated, unsupported, or uses an unknown threat vocabulary.
    pub fn from_document(value: &Value) -> Result<Self> {
        if value["version"].as_u64() != Some(2)
            || value["threat_vocabulary"] != serde_json::to_value(THREAT_CLASSES)?
        {
            return Err(Error::new(
                "Hero has no supported situational policy or threat vocabulary",
            ));
        }
        let rows = array(&value["branches"])?;
        if rows.len() > 7 {
            return Err(Error::new("Hero has more than seven situational branches"));
        }
        let abstentions: Vec<String> = serde_json::from_value(value["abstentions"].clone())?;
        if abstentions.iter().any(|reason| reason.trim().is_empty())
            || (rows.is_empty() && abstentions.is_empty())
        {
            return Err(Error::new(
                "Situational policy requires admitted branches or explicit abstention reasons",
            ));
        }
        let branches = rows
            .iter()
            .map(SituationalBranch::from_document)
            .collect::<Result<Vec<_>>>()?;
        if branches
            .iter()
            .map(|branch| branch.content().item_id)
            .collect::<BTreeSet<_>>()
            .len()
            != branches.len()
        {
            return Err(Error::new("Situational policy repeats an item"));
        }
        Ok(Self {
            branches,
            abstentions,
        })
    }

    #[must_use]
    pub fn branches(&self) -> &[SituationalBranch] {
        &self.branches
    }

    #[must_use]
    pub fn abstentions(&self) -> &[String] {
        &self.abstentions
    }
}
