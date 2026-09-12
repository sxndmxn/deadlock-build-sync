use std::collections::BTreeMap;

use deadlock_data::{Error, Result};
use deadlock_input::ItemGraph;

/// # Errors
/// Returns an error when a referenced item is absent from the current assets.
pub fn is_item_or_upgrade_owned(graph: &ItemGraph, item_id: u64, owned: &[u64]) -> Result<bool> {
    graph.require(item_id)?;
    if owned.contains(&item_id) {
        return Ok(true);
    }
    for parent in owned {
        if graph.transitive_components(*parent)?.contains(&item_id) {
            return Ok(true);
        }
    }
    Ok(false)
}

/// Associates each component purchase with its final inventory item.
///
/// # Errors
/// Returns an error when the path contains an unknown item.
pub fn resolve_route_targets(graph: &ItemGraph, path: &[u64]) -> Result<Vec<u64>> {
    let mut owned = BTreeMap::<u64, Vec<usize>>::new();
    for (index, item) in path.iter().enumerate() {
        graph.require(*item)?;
        let mut purchases = vec![index];
        for component in graph.components(*item)? {
            purchases.extend(owned.remove(component).unwrap_or_default());
        }
        owned.entry(*item).or_default().extend(purchases);
    }
    let mut targets = path.to_vec();
    for (target, purchases) in owned {
        for index in purchases {
            targets[index] = target;
        }
    }
    Ok(targets)
}

/// # Errors
/// Returns an error when a path or inventory item is absent from the current assets.
pub fn find_first_incomplete_checkpoint(
    graph: &ItemGraph,
    path: &[u64],
    owned: &[u64],
) -> Result<usize> {
    let targets = resolve_route_targets(graph, path)?;
    for (index, item) in path.iter().enumerate() {
        if !is_item_or_upgrade_owned(graph, targets[index], owned)? && !owned.contains(item) {
            return Ok(index);
        }
    }
    Ok(path.len())
}

/// # Errors
/// Returns an error when a selected purchase precedes a required core item or component.
pub fn validate_purchase_positions(
    graph: &ItemGraph,
    path: &[u64],
    positions: &BTreeMap<u64, usize>,
    owned: &[u64],
) -> Result<()> {
    for (item, index) in positions {
        let suffix = path
            .get(*index..)
            .ok_or_else(|| Error::new("Purchase position must be within the default path"))?;
        let components = graph.transitive_components(*item)?;
        for value in suffix {
            if components.contains(value) && !is_item_or_upgrade_owned(graph, *value, owned)? {
                return Err(Error::new(
                    "Purchase position precedes a required core item",
                ));
            }
        }
        if components.iter().any(|component| {
            positions
                .get(component)
                .is_some_and(|position| position > index)
        }) {
            return Err(Error::new(
                "Selected upgrade precedes its selected component",
            ));
        }
    }
    Ok(())
}
