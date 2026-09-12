use std::collections::BTreeSet;

use deadlock_data::{Error, Result, array, count_ratio, object};
use serde_json::Value;

use crate::evidence_values::{close, finite, integer};

/// # Errors
/// Returns an error when item pools or purchase timing differ from the frozen discovery evidence.
pub fn validate_frozen_pool(document: &Value, discovery: &Value) -> Result<()> {
    let frozen = &discovery["frozen_guide"];
    let tier = &document["tier_policy"];
    let pool = object(&frozen["pool"])?;
    let statistics = object(&frozen["pool_statistics"])?;
    if pool.len() != 4 || (1..=4).any(|tier| !pool.contains_key(&tier.to_string())) {
        return Err(Error::new(
            "Frozen discovery has no complete item pool; run refresh-evidence",
        ));
    }
    if tier["item_ids_by_tier"] != frozen["pool"]
        || tier["statistics"] != frozen["pool_statistics"]
        || tier["source_fold"].as_str() != Some("discovery")
    {
        return Err(Error::new(
            "Item pool differs from frozen discovery evidence",
        ));
    }
    let population = integer(&frozen["discovery_buyers"], "discovery buyers", 100)?;
    let path = array(&frozen["path"])?;
    let mut seen = BTreeSet::new();
    for row in pool.values() {
        let items = array(row)?;
        if items.len() > 10 {
            return Err(Error::new("Frozen discovery pool exceeds its tier limits"));
        }
        for value in items {
            let id = integer(value, "pool item", 1)?;
            let stats = statistics
                .get(&id.to_string())
                .ok_or_else(|| Error::new("Frozen pool item has no statistics"))?;
            validate_pool_item(stats, population)?;
            if !seen.insert(id) || path.contains(value) {
                return Err(Error::new(
                    "Frozen item pool repeats an item or contains a default path item",
                ));
            }
        }
    }
    if document["purchase_timing"] != frozen["purchase_timing"] {
        return Err(Error::new(
            "Purchase timing differs from the frozen item pool",
        ));
    }
    Ok(())
}

fn validate_pool_item(stats: &Value, population: u64) -> Result<()> {
    object(stats)?;
    let buyers = integer(&stats["buyers"], "discovery item buyers", 20)?;
    let adoption = finite(&stats["adoption"], "discovery item adoption")?;
    if buyers > population || !close(adoption, count_ratio(buyers, population)?, 0.0) {
        return Err(Error::new("Frozen item pool has invalid ownership support"));
    }
    Ok(())
}
