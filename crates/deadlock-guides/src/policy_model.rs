use std::collections::BTreeSet;

use deadlock_data::{Error, Result, fingerprint, object};
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::policy_cards::{CoreAlternativeCard, CounterCard};
use crate::policy_claim::EvidenceClaim;
use crate::policy_guard::BranchCondition;
use crate::policy_node::{NodeKind, PolicyNode};

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum AbstentionReason {
    #[serde(rename = "stale_or_incomplete_mechanics")]
    StaleMechanics,
    #[serde(rename = "inadequate_support_or_overlap")]
    InadequateSupport,
    #[serde(rename = "evidence_conflict")]
    EvidenceConflict,
    #[serde(rename = "illegal_path")]
    IllegalPath,
    #[serde(rename = "unclear_threat")]
    UnclearThreat,
    #[serde(rename = "out_of_distribution_state")]
    OutOfDistribution,
    #[serde(rename = "telemetry_failure")]
    TelemetryFailure,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Abstention {
    pub reason: AbstentionReason,
    pub detail: String,
    #[serde(default)]
    pub node_id: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BuildPolicyContent {
    pub schema_version: u8,
    pub hero_id: u64,
    pub variant: String,
    pub invariant_kit_id: String,
    pub strategic_role: String,
    pub snapshot_id: String,
    pub entry: String,
    pub nodes: Vec<PolicyNode>,
    pub evidence: Vec<EvidenceClaim>,
    #[serde(default)]
    pub ability_plan: Vec<PolicyNode>,
    #[serde(default)]
    pub abstentions: Vec<Abstention>,
    #[serde(default)]
    pub counter_cards: Vec<CounterCard>,
    #[serde(default)]
    pub core_alternatives: Vec<CoreAlternativeCard>,
    #[serde(default = "default_path_id")]
    pub path_id: String,
    #[serde(default = "default_path_label")]
    pub path_label: String,
}

fn default_path_id() -> String {
    "default".into()
}
fn default_path_label() -> String {
    "Evidence Default".into()
}

#[derive(Clone, Debug)]
pub struct BuildPolicy {
    content: BuildPolicyContent,
    policy_id: String,
}

impl BuildPolicy {
    /// # Errors
    /// Returns an error when policy identity, nodes, claims, or evidence cards fail structural validation.
    pub fn new(mut content: BuildPolicyContent) -> Result<Self> {
        normalize_branches(&mut content);
        validate_identity(&content)?;
        validate_claims(&content)?;
        validate_cards(&content)?;
        let policy_id = fingerprint(&serde_json::to_value(&content)?)?;
        Ok(Self { content, policy_id })
    }

    /// # Errors
    /// Returns an error when the sidecar has unknown fields, invalid values, or an incorrect fingerprint.
    pub fn from_document(value: &Value) -> Result<Self> {
        let mut payload = object(value)?.clone();
        let expected = payload.remove("policy_id").filter(|value| !value.is_null());
        let expected = expected
            .as_ref()
            .map(|value| {
                value
                    .as_str()
                    .ok_or_else(|| Error::new("Policy fingerprint must be a string"))
            })
            .transpose()?;
        let policy = Self::new(serde_json::from_value(payload.into())?)?;
        if expected.is_some_and(|expected| expected != policy.policy_id) {
            return Err(Error::new("Policy fingerprint does not match its contents"));
        }
        Ok(policy)
    }

    #[must_use]
    pub const fn content(&self) -> &BuildPolicyContent {
        &self.content
    }

    #[must_use]
    pub fn policy_id(&self) -> &str {
        &self.policy_id
    }

    /// # Errors
    /// Returns an error when JSON serialization fails.
    pub fn to_document(&self, include_policy_id: bool) -> Result<Value> {
        let mut value = serde_json::to_value(&self.content)?;
        if include_policy_id {
            value["policy_id"] = self.policy_id.clone().into();
        }
        Ok(value)
    }
}

fn normalize_branches(content: &mut BuildPolicyContent) {
    for node in content.nodes.iter_mut().chain(&mut content.ability_plan) {
        for branch in &mut node.branches {
            if let BranchCondition::All(guards) = &mut branch.when
                && guards.len() == 1
                && let Some(guard) = guards.pop()
            {
                branch.when = BranchCondition::Guard(guard);
            }
        }
    }
}

fn validate_identity(content: &BuildPolicyContent) -> Result<()> {
    if !(1..=5).contains(&content.schema_version) || content.hero_id == 0 {
        return Err(Error::new(
            "Policy has an unsupported schema or hero identifier",
        ));
    }
    let identity = [
        &content.variant,
        &content.invariant_kit_id,
        &content.strategic_role,
        &content.snapshot_id,
        &content.entry,
        &content.path_id,
        &content.path_label,
    ];
    if identity.iter().any(|value| value.trim().is_empty()) {
        return Err(Error::new("Policy identity fields must not be empty"));
    }
    let mut node_ids = BTreeSet::new();
    for node in content.nodes.iter().chain(&content.ability_plan) {
        node.validate()?;
        if !node_ids.insert(&node.node_id) {
            return Err(Error::new("Policy node identifiers must be unique"));
        }
    }
    if !content
        .nodes
        .iter()
        .any(|node| node.node_id == content.entry)
    {
        return Err(Error::new("Policy entry does not resolve"));
    }
    if content
        .ability_plan
        .iter()
        .any(|node| node.kind != NodeKind::Ability)
    {
        return Err(Error::new("Ability plan can contain only ability nodes"));
    }
    if content
        .abstentions
        .iter()
        .any(|row| row.detail.trim().is_empty())
    {
        return Err(Error::new("Abstention detail must not be empty"));
    }
    Ok(())
}

fn validate_claims(content: &BuildPolicyContent) -> Result<()> {
    let mut ids = BTreeSet::new();
    for claim in &content.evidence {
        claim.validate()?;
        if !ids.insert(&claim.claim_id) || claim.snapshot_id != content.snapshot_id {
            return Err(Error::new(
                "Policy claim has a duplicate identifier or stale snapshot",
            ));
        }
    }
    Ok(())
}

fn validate_cards(content: &BuildPolicyContent) -> Result<()> {
    let claims = content
        .evidence
        .iter()
        .map(|claim| claim.claim_id.as_str())
        .collect::<BTreeSet<_>>();
    let actions = content
        .nodes
        .iter()
        .filter(|node| node.kind == NodeKind::Purchase && node.optional)
        .map(|node| (node.item_id, node.evidence_ref.as_deref()))
        .collect::<BTreeSet<_>>();
    let mut ids = BTreeSet::new();
    for card in &content.counter_cards {
        card.validate()?;
        if !ids.insert(card.item_id)
            || !claims.contains(card.evidence_ref.as_str())
            || !actions.contains(&(Some(card.item_id), Some(card.evidence_ref.as_str())))
        {
            return Err(Error::new(
                "Counter card has duplicate items or missing evidence and optional actions",
            ));
        }
    }
    validate_alternatives(content, &claims)
}

fn validate_alternatives(content: &BuildPolicyContent, claims: &BTreeSet<&str>) -> Result<()> {
    if content.schema_version == 1 && !content.core_alternatives.is_empty() {
        return Err(Error::new(
            "Policy schema 1 cannot contain core alternatives",
        ));
    }
    let default = content
        .nodes
        .iter()
        .filter(|node| node.kind == NodeKind::Purchase && !node.optional)
        .filter_map(|node| node.item_id)
        .collect::<BTreeSet<_>>();
    let mut ids = BTreeSet::new();
    for card in &content.core_alternatives {
        card.validate()?;
        if !ids.insert(card.item_id)
            || !claims.contains(card.evidence_ref.as_str())
            || default.contains(&card.item_id)
            || !default.contains(&card.comparator_item_id)
        {
            return Err(Error::new(
                "Core alternative card has duplicate items, missing evidence, or an invalid replacement",
            ));
        }
    }
    Ok(())
}
