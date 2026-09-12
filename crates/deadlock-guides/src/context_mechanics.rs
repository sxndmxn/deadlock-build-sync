use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Error, Result, array, fingerprint, object};
use deadlock_input::extract_asset_mechanics;
use serde_json::{Map, Value};

/// # Errors
/// Returns an error when a referenced item has no current asset or a malformed identity.
pub fn build_item_mechanics_catalog(
    assets: &[Value],
    item_ids: &BTreeSet<u64>,
) -> Result<Map<String, Value>> {
    let indexed = assets
        .iter()
        .filter_map(|asset| asset["id"].as_u64().map(|id| (id, asset)))
        .collect::<BTreeMap<_, _>>();
    item_ids
        .iter()
        .map(|id| {
            let asset = indexed
                .get(id)
                .ok_or_else(|| Error::new(format!("Item mechanics asset is absent: {id}")))?;
            Ok((id.to_string(), extract_asset_mechanics(asset)?))
        })
        .collect()
}

/// # Errors
/// Returns an error when a referenced mechanics record is absent or cannot serialize.
pub fn calculate_item_mechanics_sha256(
    ids: &[u64],
    catalog: &Map<String, Value>,
) -> Result<String> {
    let records = ids
        .iter()
        .map(|id| {
            let key = id.to_string();
            let record = catalog
                .get(&key)
                .ok_or_else(|| Error::new(format!("Item mechanics record is absent: {id}")))?;
            Ok((key, record.clone()))
        })
        .collect::<Result<Map<_, _>>>()?;
    fingerprint(&records.into())
}

pub fn validate_mechanics_catalog(catalog: &Map<String, Value>) -> Result<()> {
    for (key, value) in catalog {
        let id = key.parse::<u64>().ok().filter(|id| *id > 0);
        if id.is_none_or(|id| id.to_string() != *key) || !value.is_object() {
            return Err(Error::new(
                "Item mechanics catalog has an invalid identifier or record",
            ));
        }
    }
    Ok(())
}

pub fn validate_hero_item_mechanics(
    entry: &Value,
    catalog: &Map<String, Value>,
) -> Result<Vec<u64>> {
    let ids: Vec<u64> = serde_json::from_value(entry["item_mechanics_ids"].clone())?;
    if ids.contains(&0) || ids.windows(2).any(|pair| pair[0] >= pair[1]) {
        return Err(Error::new(
            "Hero mechanics identifiers must be positive, sorted, and unique",
        ));
    }
    let mut expected = BTreeSet::new();
    for item in context_item_records(entry)? {
        if item.get("mechanics").is_some() {
            return Err(Error::new("Context item contains duplicate mechanics"));
        }
        let id = item["item_id"]
            .as_u64()
            .filter(|id| *id > 0)
            .ok_or_else(|| Error::new("Context item has no positive identifier"))?;
        expected.insert(id);
    }
    if ids.iter().copied().collect::<BTreeSet<_>>() != expected
        || entry.get("hero_description").is_some()
        || entry.get("abilities").is_some()
    {
        return Err(Error::new(
            "Context mechanics references differ from the item or hero records",
        ));
    }
    if entry["item_mechanics_sha256"] != calculate_item_mechanics_sha256(&ids, catalog)? {
        return Err(Error::new("Context item mechanics fingerprint differs"));
    }
    Ok(ids)
}

fn context_item_records(entry: &Value) -> Result<Vec<&Value>> {
    let mut records = Vec::new();
    for field in ["items", "optional_core_substitution_cards"] {
        if let Some(items) = entry["core"].get(field) {
            records.extend(array(items)?);
        }
    }
    if let Some(tiers) = entry.get("tiers") {
        for items in object(tiers)?.values() {
            records.extend(array(items)?);
        }
    }
    Ok(records)
}
