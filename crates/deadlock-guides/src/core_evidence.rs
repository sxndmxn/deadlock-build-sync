use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Error, Result, array, object};
use serde_json::{Map, Value};

use crate::core_alternative::CoreAlternativeEvidence;
use crate::evidence_values::{add_counts, integer};

#[derive(Clone, Debug)]
pub struct CorePolicyContent {
    pub backbone_item_ids: Vec<u64>,
    pub default_item_ids: Vec<u64>,
    pub backbone_matches: u64,
    pub backbone_fold_matches: BTreeMap<String, u64>,
    pub default_matches: u64,
    pub default_fold_matches: BTreeMap<String, u64>,
    pub alternatives: Vec<CoreAlternativeEvidence>,
    pub candidate_audit: Vec<Value>,
    pub evaluation: Map<String, Value>,
}

#[derive(Clone, Debug)]
pub struct CorePolicyEvidence(CorePolicyContent);

impl CorePolicyEvidence {
    /// # Errors
    /// Returns an error when the core policy fails membership, cohort, or comparative evidence requirements.
    pub fn from_document(value: &Value, item_ids: &BTreeSet<u64>, eligible: u64) -> Result<Self> {
        if value["version"].as_u64() != Some(3) {
            return Err(Error::new("Hero has no supported core policy"));
        }
        let backbone_item_ids = parse_distinct_ids(&value["backbone_item_ids"])?;
        let default_item_ids = parse_distinct_ids(&value["default_item_ids"])?;
        validate_membership(&backbone_item_ids, &default_item_ids, item_ids)?;
        let (backbone_matches, backbone_fold_matches) = parse_support(value, "backbone", eligible)?;
        let (default_matches, default_fold_matches) = parse_support(value, "default", eligible)?;
        let default = default_item_ids.iter().copied().collect();
        let alternatives = array(&value["alternatives"])?
            .iter()
            .map(|value| CoreAlternativeEvidence::from_document(value, item_ids, &default))
            .collect::<Result<Vec<_>>>()?;
        validate_alternatives(&alternatives, default_item_ids.len())?;
        let candidate_audit = array(&value["candidate_audit"])?
            .iter()
            .map(|value| {
                object(value)?;
                Ok(value.clone())
            })
            .collect::<Result<Vec<_>>>()?;
        Ok(Self(CorePolicyContent {
            backbone_item_ids,
            default_item_ids,
            backbone_matches,
            backbone_fold_matches,
            default_matches,
            default_fold_matches,
            alternatives,
            candidate_audit,
            evaluation: object(&value["evaluation"])?.clone(),
        }))
    }

    #[must_use]
    pub const fn content(&self) -> &CorePolicyContent {
        &self.0
    }
}

pub fn parse_distinct_ids(value: &Value) -> Result<Vec<u64>> {
    let ids = array(value)?
        .iter()
        .map(|value| integer(value, "item identifier", 1))
        .collect::<Result<Vec<_>>>()?;
    if ids.iter().collect::<BTreeSet<_>>().len() != ids.len() {
        return Err(Error::new("Item identifiers must be distinct"));
    }
    Ok(ids)
}

fn validate_membership(backbone: &[u64], default: &[u64], items: &BTreeSet<u64>) -> Result<()> {
    if !(3..=6).contains(&backbone.len())
        || default.len() < backbone.len()
        || default.len() > 9
        || backbone.iter().any(|id| !default.contains(id))
        || default.iter().any(|id| !items.contains(id))
    {
        return Err(Error::new("Hero has invalid core policy membership"));
    }
    Ok(())
}

fn parse_support(
    value: &Value,
    label: &str,
    eligible: u64,
) -> Result<(u64, BTreeMap<String, u64>)> {
    let raw = &value[format!("{label}_fold_matches")];
    object(raw)?;
    let mut folds = BTreeMap::new();
    for fold in ["train", "validation", "test"] {
        let minimum = if fold == "train" { 20 } else { 0 };
        folds.insert(
            fold.into(),
            integer(&raw[fold], "core fold support", minimum)?,
        );
    }
    let matches = integer(&value[format!("{label}_matches")], "core support", 0)?;
    if matches != add_counts(folds["train"], folds["validation"])? || matches > eligible {
        return Err(Error::new(
            "Core support is inconsistent with its fold counts or eligible cohort",
        ));
    }
    Ok((matches, folds))
}

fn validate_alternatives(alternatives: &[CoreAlternativeEvidence], core_len: usize) -> Result<()> {
    if alternatives.len() > 10
        || alternatives
            .iter()
            .map(|alternative| alternative.content().item_id)
            .collect::<BTreeSet<_>>()
            .len()
            != alternatives.len()
        || alternatives
            .iter()
            .any(|alternative| alternative.content().stage > core_len)
    {
        return Err(Error::new("Hero has invalid core alternatives"));
    }
    Ok(())
}
