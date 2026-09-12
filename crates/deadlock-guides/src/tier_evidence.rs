use std::collections::BTreeMap;

use deadlock_data::{Error, Result, object};
use serde_json::Value;

use crate::core_evidence::parse_distinct_ids;
use crate::item_evidence::ItemEvidence;
use crate::item_evidence_content::ItemEvidenceContent;

#[derive(Clone, Debug)]
pub struct TierPolicyEvidence {
    item_ids_by_tier: BTreeMap<u8, Vec<u64>>,
    discovery_pool: bool,
}

impl TierPolicyEvidence {
    /// # Errors
    /// Returns an error when the tier pool has unsupported, duplicate, or incorrectly classified items.
    pub fn from_document(value: &Value, items: &[ItemEvidence]) -> Result<Self> {
        if value["version"].as_u64() != Some(1) {
            return Err(Error::new("Hero has no supported tier policy"));
        }
        let membership = object(&value["item_ids_by_tier"])?;
        if membership.len() != 4 || (1..=4).any(|tier| !membership.contains_key(&tier.to_string()))
        {
            return Err(Error::new("Hero has an incomplete tier policy"));
        }
        let discovery_pool = value["source_fold"].as_str() == Some("discovery");
        let by_id = items
            .iter()
            .map(|item| (item.content().item_id, item.content()))
            .collect::<BTreeMap<_, _>>();
        let mut item_ids_by_tier = BTreeMap::new();
        for tier in 1..=4_u8 {
            let ids = parse_distinct_ids(&membership[&tier.to_string()])?;
            if ids.len() > 10 || (!discovery_pool && ids.is_empty()) {
                return Err(Error::new(format!(
                    "Tier {tier} membership exceeds its limits"
                )));
            }
            if ids.iter().any(|id| {
                by_id
                    .get(id)
                    .is_none_or(|item| !supported_pool_item(item, tier, discovery_pool))
            }) {
                return Err(Error::new(format!(
                    "Tier {tier} contains an unsupported item"
                )));
            }
            item_ids_by_tier.insert(tier, ids);
        }
        Ok(Self {
            item_ids_by_tier,
            discovery_pool,
        })
    }

    #[must_use]
    pub const fn item_ids_by_tier(&self) -> &BTreeMap<u8, Vec<u64>> {
        &self.item_ids_by_tier
    }

    #[must_use]
    pub const fn discovery_pool(&self) -> bool {
        self.discovery_pool
    }
}

fn supported_pool_item(item: &ItemEvidenceContent, tier: u8, discovery: bool) -> bool {
    item.tier == u64::from(tier)
        && item.training_adopter_matches >= 20
        && (discovery
            || (item.validation_adopter_matches >= 20
                && item.training_adoption.min(item.validation_adoption) >= 0.05
                && (item.training_adoption - item.validation_adoption).abs() <= 0.10))
}
