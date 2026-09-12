use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Error, Result};
use deadlock_input::ItemGraph;

use crate::automatic_branch::AutomaticBranch;
use crate::component_schedule::{PurchasePriorities, schedule_component_path};
use crate::discovery_evidence::frozen_windows;
use crate::hero_evidence::HeroBuildEvidence;
use crate::inventory::{InventoryState, purchase_item};
use crate::item_evidence::{ItemEvidence, nondecreasing_window_schedule};
use crate::purchase_plan_types::PurchaseState;
use crate::purchase_planner::plan_purchases;

pub type ItemEvidenceIndex<'evidence> = BTreeMap<u64, &'evidence ItemEvidence>;

pub fn expand_component_path(
    graph: &ItemGraph,
    targets: &[u64],
    evidence: &ItemEvidenceIndex<'_>,
) -> Result<Vec<u64>> {
    let priorities = evidence
        .iter()
        .map(|(id, item)| {
            let item = item.content();
            (
                *id,
                (
                    item.selection_median_valid_buy_net_worth
                        .unwrap_or(f64::INFINITY),
                    item.selection_median_buy_time_s.unwrap_or(f64::INFINITY),
                    *id,
                ),
            )
        })
        .collect::<PurchasePriorities>();
    schedule_component_path(graph, targets, &priorities)
}

pub fn validate_component_path(
    graph: &ItemGraph,
    evidence: &ItemEvidenceIndex<'_>,
    path: &[u64],
    core: &[u64],
) -> Result<()> {
    let mut state = InventoryState::default();
    for id in path {
        if !evidence.contains_key(id) {
            return Err(Error::new(format!(
                "Purchase path item {id} has no evidence"
            )));
        }
        if graph
            .components(*id)?
            .iter()
            .any(|component| !state.owned().contains(component))
        {
            return Err(Error::new(format!(
                "Purchase path item {id} precedes its components"
            )));
        }
        state = purchase_item(graph, &state, *id, 0)?;
    }
    let expected = core.iter().copied().collect::<BTreeSet<_>>();
    if expected.len() != core.len()
        || state.owned().iter().copied().collect::<BTreeSet<_>>() != expected
    {
        return Err(Error::new(
            "Purchase path does not end with the required core",
        ));
    }
    Ok(())
}

pub fn validate_selected_path(
    graph: &ItemGraph,
    evidence: &HeroBuildEvidence,
    items: &ItemEvidenceIndex<'_>,
) -> Result<()> {
    let path = &evidence.sequence_policy.content().default_path;
    if evidence.discovery["frozen_guide"].is_object() {
        frozen_windows(&evidence.discovery["frozen_guide"])?;
    } else {
        let bounds = items
            .iter()
            .filter_map(|(id, item)| item.reliable_purchase_window().map(|window| (*id, window)))
            .collect();
        if nondecreasing_window_schedule(path, &bounds).is_none() {
            return Err(Error::new(
                "Purchase path violates first-ownership soul windows",
            ));
        }
    }
    validate_component_path(
        graph,
        items,
        path,
        &evidence.core_policy.content().default_item_ids,
    )
}

pub fn validate_situational_paths(
    graph: &ItemGraph,
    evidence: &HeroBuildEvidence,
    items: &ItemEvidenceIndex<'_>,
) -> Result<()> {
    for branch in evidence.situational_policy.branches() {
        let branch = branch.content();
        let core = evidence
            .core_policy
            .content()
            .default_item_ids
            .iter()
            .map(|id| {
                if *id == branch.comparator_item_id {
                    branch.item_id
                } else {
                    *id
                }
            })
            .collect::<Vec<_>>();
        let path = expand_component_path(graph, &core, items)?;
        validate_component_path(graph, items, &path, &core)?;
    }
    Ok(())
}

pub fn validate_substitution_paths(
    graph: &ItemGraph,
    branches: &[AutomaticBranch],
    core: &[u64],
) -> Result<()> {
    let core = core.iter().copied().collect::<BTreeSet<_>>();
    for branch in branches
        .iter()
        .filter(|branch| !branch.substituted_core.is_empty())
    {
        if branch.substitution_evidence.is_empty() {
            return Err(Error::new(
                "Core substitution has no separate admission evidence",
            ));
        }
        let replacement = branch
            .substituted_core
            .iter()
            .copied()
            .collect::<BTreeSet<_>>();
        let plan = plan_purchases(
            graph,
            &branch.substituted_path,
            &branch.substituted_core,
            &BTreeMap::new(),
            &PurchaseState::default(),
        )?;
        if core.difference(&replacement).copied().collect::<Vec<_>>() != [branch.comparator_item_id]
            || replacement.difference(&core).copied().collect::<Vec<_>>() != [branch.item_id]
            || plan
                .actions
                .iter()
                .map(|step| step.item_id)
                .collect::<Vec<_>>()
                != branch.substituted_path
            || plan
                .final_inventory
                .iter()
                .copied()
                .collect::<BTreeSet<_>>()
                != replacement
        {
            return Err(Error::new(
                "Core substitution has an invalid purchase path or final inventory",
            ));
        }
    }
    Ok(())
}
