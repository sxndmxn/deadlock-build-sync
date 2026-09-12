use std::collections::BTreeMap;

use deadlock_data::{Error, Result};
use deadlock_input::ItemGraph;

use crate::automatic_branch::{AutomaticBranch, AutomaticCondition, BranchTrigger};
use crate::decision_state::{DecisionStateContent, recent_observation};
use crate::purchase_guidance_types::PurchaseGuidance;
use crate::purchase_plan_types::PurchaseState;
use crate::purchase_planner::plan_purchases;
use crate::purchase_route::{find_first_incomplete_checkpoint, is_item_or_upgrade_owned};

#[derive(Debug)]
pub struct SelectedPurchaseRoute {
    pub path: Vec<u64>,
    pub core: Vec<u64>,
    pub positions: BTreeMap<u64, usize>,
    pub source: &'static str,
    pub branch: Option<AutomaticBranch>,
}

pub fn selected_purchase_positions(
    guidance: &PurchaseGuidance,
    state: &DecisionStateContent,
) -> Result<BTreeMap<u64, usize>> {
    let mut positions = BTreeMap::new();
    for id in &state.selected_optional_items {
        let card = guidance
            .choices
            .iter()
            .find(|card| card.item_id == *id)
            .ok_or_else(|| Error::new("Selected item is outside the build item pool"))?;
        let position = state
            .placement_overrides
            .get(id)
            .copied()
            .or(card.after_step)
            .ok_or_else(|| {
                Error::new(format!(
                    "Timing is unknown for {}; supply placement_overrides",
                    card.name
                ))
            })?;
        positions.insert(*id, position);
    }
    Ok(positions)
}

pub fn select_purchase_route(
    guidance: &PurchaseGuidance,
    state: &DecisionStateContent,
    graph: &ItemGraph,
) -> Result<SelectedPurchaseRoute> {
    let mut route = SelectedPurchaseRoute {
        path: guidance
            .default_path
            .actions
            .iter()
            .map(|step| step.item_id)
            .collect(),
        core: guidance.core_ids.clone(),
        positions: selected_purchase_positions(guidance, state)?,
        source: "default path",
        branch: None,
    };
    let mut branches = guidance.automatic_branches.iter().collect::<Vec<_>>();
    branches.sort_by(|a, b| {
        b.lower_bound
            .total_cmp(&a.lower_bound)
            .then(b.support.cmp(&a.support))
            .then(a.item_id.cmp(&b.item_id))
    });
    if let Some(id) = state.core_substitution_item_id {
        let branch = branches.iter().copied().find(|branch| branch.item_id == id && !branch.substituted_core.is_empty())
            .filter(|_| route.positions.contains_key(&id)).ok_or_else(|| Error::new("Selected core substitution requires admitted branch evidence and an explicit item selection"))?;
        route.path.clone_from(&branch.substituted_path);
        route.core.clone_from(&branch.substituted_core);
        route.source = "explicit core substitution";
        route.branch = Some(branch.clone());
        return Ok(route);
    }
    if !route.positions.is_empty() {
        route.source = "explicit selection";
        return Ok(route);
    }
    let checkpoint = find_first_incomplete_checkpoint(graph, &route.path, &state.inventory.items)?;
    for branch in branches {
        if branch.after_step != checkpoint
            || !branch_matches(branch, state)?
            || is_item_or_upgrade_owned(graph, branch.item_id, &state.inventory.items)?
        {
            continue;
        }
        let candidate = SelectedPurchaseRoute {
            path: if branch.substituted_path.is_empty() {
                route.path.clone()
            } else {
                branch.substituted_path.clone()
            },
            core: if branch.substituted_core.is_empty() {
                route.core.clone()
            } else {
                branch.substituted_core.clone()
            },
            positions: BTreeMap::from([(branch.item_id, branch.after_step)]),
            source: "admitted matching branch",
            branch: Some(branch.clone()),
        };
        if plan_purchases(
            graph,
            &candidate.path,
            &candidate.core,
            &candidate.positions,
            &purchase_state(state),
        )
        .is_ok()
        {
            return Ok(candidate);
        }
    }
    Ok(route)
}

fn branch_matches(branch: &AutomaticBranch, state: &DecisionStateContent) -> Result<bool> {
    if branch.condition == AutomaticCondition::RelativeWealth {
        let ratio = state
            .economy
            .as_ref()
            .map(|economy| economy.relative_wealth(state.clock_s))
            .transpose()?
            .flatten();
        return Ok(ratio.is_some_and(|ratio| match &branch.value {
            BranchTrigger::Name(value) if value == "behind" => ratio < 0.90,
            BranchTrigger::Name(value) if value == "ahead" => ratio > 1.10,
            BranchTrigger::Name(value) if value == "even" => (0.90..=1.10).contains(&ratio),
            _ => false,
        }));
    }
    if !recent_observation(state.clock_s, state.enemy_observed_at_s) {
        return Ok(false);
    }
    let observations = if branch.condition == AutomaticCondition::EnemyHero {
        &state.enemy_hero_ids
    } else {
        &state.enemy_item_ids
    };
    Ok(match branch.value {
        BranchTrigger::Identifier(id) => observations.contains(&id),
        BranchTrigger::Name(_) => false,
    })
}

pub fn purchase_state(state: &DecisionStateContent) -> PurchaseState {
    PurchaseState {
        owned: state.inventory.items.clone(),
        liquid_souls: Some(state.liquid_souls),
        flex: state.inventory.flex_slots,
    }
}
