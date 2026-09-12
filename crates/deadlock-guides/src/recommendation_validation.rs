use std::collections::BTreeSet;

use deadlock_data::{Error, Result};
use deadlock_input::ItemGraph;
use serde_json::Value;

use crate::decision_state::DecisionStateContent;
use crate::evidence_catalog::BuildEvidenceCatalog;
use crate::inventory::{BASE_INVENTORY_SLOTS, InventoryState, MAX_ACTIVE_ITEMS};
use crate::mechanic_responses::classify_observed_item_threats;

pub fn validate_evidence_identity(
    catalog: &BuildEvidenceCatalog,
    state: &DecisionStateContent,
) -> Result<()> {
    let metadata = catalog.metadata();
    if state.build_evidence_id != metadata.artifact_id {
        return Err(Error::new(
            "Decision state uses a different evidence artifact",
        ));
    }
    if state.client_version != metadata.client_version
        || metadata.patch.get("identity").and_then(Value::as_str)
            != Some(state.patch_identity.as_str())
        || metadata
            .cohort
            .get("match_mode")
            .and_then(Value::as_str)
            .is_none_or(|mode| !mode.eq_ignore_ascii_case(&state.match_mode))
        || metadata
            .cohort
            .get("game_mode")
            .and_then(Value::as_str)
            .is_none_or(|mode| !mode.eq_ignore_ascii_case(&state.game_mode))
    {
        return Err(Error::new(
            "Decision state uses a different evidence artifact, patch, client version, or cohort",
        ));
    }
    let hero = catalog
        .heroes()
        .get(&state.hero_id)
        .ok_or_else(|| Error::new("Decision state hero is absent from build evidence"))?;
    let cohort = hero.builds.first().map(|build| build.cohort.content());
    let minimum = cohort
        .map(|cohort| u64::from(cohort.minimum_badge.badge()))
        .or_else(|| metadata.cohort.get("minimum_badge")?.as_u64());
    let maximum = cohort
        .map(|cohort| u64::from(cohort.maximum_badge.badge()))
        .or_else(|| metadata.cohort.get("maximum_badge")?.as_u64());
    if minimum
        .zip(maximum)
        .is_none_or(|(minimum, maximum)| !(minimum..=maximum).contains(&state.average_badge))
    {
        return Err(Error::new(
            "Decision state rank is outside the evidence cohort",
        ));
    }
    Ok(())
}

pub fn validate_inventory(
    state: &DecisionStateContent,
    graph: &ItemGraph,
) -> Result<InventoryState> {
    let current = &state.inventory;
    let inventory = InventoryState::new(current.items.clone(), current.flex_slots)?;
    let capacity = BASE_INVENTORY_SLOTS + usize::from(current.flex_slots);
    let active = current.items.iter().try_fold(0, |active, id| {
        Ok::<_, Error>(active + usize::from(graph.require(*id)?.active))
    })?;
    if current.open_slots != capacity - current.items.len()
        || current.active_bindings != active
        || active > MAX_ACTIVE_ITEMS
    {
        return Err(Error::new(
            "Decision state slot or active-binding count is inconsistent",
        ));
    }
    let mut components = BTreeSet::new();
    for id in graph.nodes().keys() {
        components.extend(graph.components(*id)?.iter().copied());
    }
    let expected = current
        .items
        .iter()
        .filter(|id| components.contains(*id))
        .copied()
        .collect::<BTreeSet<_>>();
    if expected != current.components.iter().copied().collect() {
        return Err(Error::new(
            "Decision state component ownership is inconsistent",
        ));
    }
    Ok(inventory)
}

pub fn observed_threats(
    state: &DecisionStateContent,
    graph: &ItemGraph,
    assets: &[Value],
) -> Result<BTreeSet<String>> {
    let mut threats = state.threats.iter().cloned().collect::<BTreeSet<_>>();
    for id in &state.enemy_item_ids {
        graph.require(*id)?;
        let asset = assets
            .iter()
            .find(|asset| asset["id"].as_u64() == Some(*id))
            .ok_or_else(|| Error::new("Observed enemy item has no asset"))?;
        threats.extend(
            classify_observed_item_threats(asset)?
                .into_iter()
                .map(|threat| threat.as_str().into()),
        );
    }
    if state.inventory.active_bindings == MAX_ACTIVE_ITEMS {
        threats.insert("active_slot_burden".into());
    }
    Ok(threats)
}
