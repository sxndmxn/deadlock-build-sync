use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Error, Result, array, count_ratio};
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::item_evidence::ItemEvidence;
use crate::sequence_evidence::SequencePolicy;
use crate::tier_evidence::TierPolicyEvidence;

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PurchaseTiming {
    pub item_id: u64,
    pub buyers: u64,
    pub counts_by_checkpoint: Vec<u64>,
}

impl PurchaseTiming {
    #[must_use]
    pub fn observed_position(&self) -> Option<usize> {
        let mut selected = None;
        let mut support = 0;
        for (index, count) in self.counts_by_checkpoint.iter().enumerate() {
            if selected.is_none() || *count > support {
                selected = Some(index);
                support = *count;
            }
        }
        selected
    }

    #[must_use]
    pub fn support(&self) -> u64 {
        self.observed_position()
            .map_or(0, |position| self.counts_by_checkpoint[position])
    }

    /// # Errors
    /// Returns an error when an observation count cannot form a finite ratio.
    pub fn position(&self) -> Result<Option<usize>> {
        let support = self.support();
        if support >= 20 && count_ratio(support, self.buyers)? >= 0.1 {
            Ok(self.observed_position())
        } else {
            Ok(None)
        }
    }
}

/// # Errors
/// Returns an error when purchase timing differs from the core path, training fold, or selected item pool.
pub fn parse_purchase_timing(
    value: &Value,
    sequence: &SequencePolicy,
    tiers: &TierPolicyEvidence,
    items: &[ItemEvidence],
) -> Result<Vec<PurchaseTiming>> {
    if value.is_null() {
        return Ok(Vec::new());
    }
    if value["version"].as_u64() != Some(1) {
        return Err(Error::new("Purchase timing has an invalid version"));
    }
    let path: Vec<u64> = serde_json::from_value(value["core_path"].clone())?;
    if path != sequence.content().default_path || value["fold"].as_str() != Some("train") {
        return Err(Error::new(
            "Purchase timing differs from its core path or training fold",
        ));
    }
    let pool = tiers
        .item_ids_by_tier()
        .values()
        .flatten()
        .copied()
        .collect::<BTreeSet<_>>();
    let evidence = items
        .iter()
        .map(|item| (item.content().item_id, item.content()))
        .collect::<BTreeMap<_, _>>();
    let mut result = BTreeMap::new();
    for row in array(&value["items"])? {
        let timing: PurchaseTiming = serde_json::from_value(row.clone())?;
        let item = evidence
            .get(&timing.item_id)
            .filter(|_| pool.contains(&timing.item_id))
            .ok_or_else(|| Error::new("Purchase timing references an item outside the pool"))?;
        if timing.buyers != item.training_adopter_matches
            || timing.counts_by_checkpoint.len() != path.len() + 1
            || timing
                .counts_by_checkpoint
                .iter()
                .any(|count| *count > timing.buyers)
        {
            return Err(Error::new(
                "Purchase timing counts disagree with training evidence",
            ));
        }
        if result.insert(timing.item_id, timing).is_some() {
            return Err(Error::new("Purchase timing repeats an item"));
        }
    }
    if result.keys().copied().collect::<BTreeSet<_>>() != pool {
        return Err(Error::new("Purchase timing must cover each pool item once"));
    }
    Ok(result.into_values().collect())
}
