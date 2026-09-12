use deadlock_data::{Error, Result};
use serde::{Deserialize, Serialize};

use crate::policy_guard::PolicyBranch;

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum NodeKind {
    Purchase,
    Choice,
    Sell,
    Ability,
    Wait,
    ObjectiveGate,
    #[default]
    End,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PolicyNode {
    #[serde(rename = "id")]
    pub node_id: String,
    pub kind: NodeKind,
    #[serde(default, rename = "next")]
    pub next_id: Option<String>,
    #[serde(default)]
    pub evidence_ref: Option<String>,
    #[serde(default)]
    pub item_id: Option<u64>,
    #[serde(default)]
    pub ability_id: Option<u64>,
    #[serde(default)]
    pub level: Option<u32>,
    #[serde(default)]
    pub branches: Vec<PolicyBranch>,
    #[serde(default)]
    pub optional: bool,
    #[serde(default)]
    pub required_flex_slots: u8,
    #[serde(default)]
    pub sell_priority: Option<u32>,
    #[serde(default)]
    pub imbue_target_ability_id: Option<u64>,
    #[serde(default)]
    pub imbue_qualifier: Option<String>,
    #[serde(default = "allow_ultimate_imbue")]
    pub allow_ultimate_imbue: bool,
    #[serde(default)]
    pub unlocks_flex_slots: Option<u8>,
    #[serde(default)]
    pub earliest_time_s: Option<u64>,
    #[serde(default)]
    pub latest_time_s: Option<u64>,
    #[serde(default)]
    pub recalculation_next: Option<String>,
    #[serde(default)]
    pub annotation: String,
}

const fn allow_ultimate_imbue() -> bool {
    true
}

impl Default for PolicyNode {
    fn default() -> Self {
        Self {
            node_id: String::new(),
            kind: NodeKind::End,
            next_id: None,
            evidence_ref: None,
            item_id: None,
            ability_id: None,
            level: None,
            branches: Vec::new(),
            optional: false,
            required_flex_slots: 0,
            sell_priority: None,
            imbue_target_ability_id: None,
            imbue_qualifier: None,
            allow_ultimate_imbue: true,
            unlocks_flex_slots: None,
            earliest_time_s: None,
            latest_time_s: None,
            recalculation_next: None,
            annotation: String::new(),
        }
    }
}

impl PolicyNode {
    /// # Errors
    /// Returns an error when the node identity, action fields, branches, or constraints are invalid.
    pub fn validate(&self) -> Result<()> {
        if self.node_id.trim().is_empty() {
            return Err(Error::new("Policy node identifier must not be empty"));
        }
        self.validate_action()?;
        let choice = matches!(self.kind, NodeKind::Choice | NodeKind::ObjectiveGate);
        if choice == self.branches.is_empty() {
            return Err(Error::new(
                "Policy node has branches incompatible with its kind",
            ));
        }
        for branch in &self.branches {
            branch.validate()?;
        }
        if self.kind == NodeKind::End && self.next_id.is_some() {
            return Err(Error::new("End node has a successor"));
        }
        if self.required_flex_slots > 3 || self.sell_priority == Some(0) {
            return Err(Error::new(
                "Policy node has invalid flex slots or sale priority",
            ));
        }
        if self
            .earliest_time_s
            .zip(self.latest_time_s)
            .is_some_and(|(earliest, latest)| earliest > latest)
        {
            return Err(Error::new("Policy node has an inverted time window"));
        }
        Ok(())
    }

    fn validate_action(&self) -> Result<()> {
        let valid = match self.kind {
            NodeKind::Purchase | NodeKind::Sell => self.item_id.is_some_and(|id| id > 0),
            NodeKind::Ability => self.ability_id.is_some_and(|id| id > 0) && self.level.is_some(),
            _ => true,
        };
        if !valid {
            return Err(Error::new(
                "Policy action has an incomplete item, ability, or level",
            ));
        }
        Ok(())
    }

    #[must_use]
    pub fn successors(&self) -> Vec<&str> {
        if self.branches.is_empty() {
            self.next_id.as_deref().into_iter().collect()
        } else {
            self.branches
                .iter()
                .map(|branch| branch.next_id.as_str())
                .collect()
        }
    }
}
