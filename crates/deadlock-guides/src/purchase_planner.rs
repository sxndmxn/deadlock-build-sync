use std::collections::BTreeMap;

use deadlock_data::{Error, Result};
use deadlock_input::ItemGraph;

use crate::inventory::{InventoryState, MAX_ACTIVE_ITEMS, purchase_item};
use crate::purchase_plan_types::{PurchasePlan, PurchaseState, PurchaseStep};
use crate::purchase_route::{
    is_item_or_upgrade_owned, resolve_route_targets, validate_purchase_positions,
};

#[derive(Debug)]
struct PurchasePlanner<'graph> {
    graph: &'graph ItemGraph,
    state: InventoryState,
    actions: Vec<PurchaseStep>,
    total_cost: u64,
}

impl<'graph> PurchasePlanner<'graph> {
    fn new(graph: &'graph ItemGraph, state: &PurchaseState) -> Result<Self> {
        let state = InventoryState::new(state.owned.clone(), state.flex)?;
        validate_owned_items(graph, &state)?;
        Ok(Self {
            graph,
            state,
            actions: Vec::new(),
            total_cost: 0,
        })
    }

    fn add_item_purchases(&mut self, item_id: u64, exact: bool, depth: usize) -> Result<()> {
        if depth > 64 || self.actions.len() >= 4096 {
            return Err(Error::new(
                "Purchase plan exceeds its depth or action limit",
            ));
        }
        let satisfied = if exact {
            self.state.owned().contains(&item_id)
        } else {
            is_item_or_upgrade_owned(self.graph, item_id, self.state.owned())?
        };
        if satisfied {
            return Ok(());
        }
        for component in self.graph.components(item_id)?.to_vec() {
            self.add_item_purchases(component, true, depth + 1)?;
        }
        let incremental_cost = self
            .graph
            .incremental_cash_cost(item_id, self.state.owned())?;
        let consumed_items = self
            .graph
            .components(item_id)?
            .iter()
            .copied()
            .filter(|id| self.state.owned().contains(id))
            .collect();
        self.state = purchase_item(self.graph, &self.state, item_id, 0)?;
        self.total_cost = self
            .total_cost
            .checked_add(incremental_cost)
            .ok_or_else(|| Error::new("Purchase plan cost exceeds 64 bits"))?;
        self.actions.push(PurchaseStep {
            item_id,
            name: self.graph.require(item_id)?.name.clone(),
            incremental_cost,
            cumulative_cost: self.total_cost,
            consumed_items,
            owned_after: self.state.owned().to_vec(),
        });
        Ok(())
    }

    fn build_plan(self, liquid_souls: Option<u64>) -> PurchasePlan {
        let shortage = self
            .actions
            .first()
            .zip(liquid_souls)
            .map(|(action, souls)| action.incremental_cost.saturating_sub(souls));
        let decision = if self.actions.is_empty() {
            "complete"
        } else if shortage.is_some_and(|amount| amount > 0) {
            "save"
        } else if liquid_souls.is_some() {
            "buy"
        } else {
            "check cash"
        };
        PurchasePlan {
            actions: self.actions,
            final_inventory: self.state.owned().to_vec(),
            remaining_cost: self.total_cost,
            decision: decision.into(),
            save_souls: shortage,
        }
    }
}

fn validate_owned_items(graph: &ItemGraph, state: &InventoryState) -> Result<()> {
    let mut counts = BTreeMap::<u64, u32>::new();
    let mut active = 0;
    for id in state.owned() {
        let item = graph.require(*id)?;
        let count = counts.entry(*id).or_default();
        *count += 1;
        if *count > item.max_count || (item.unique && *count > 1) {
            return Err(Error::new("Inventory exceeds an item ownership limit"));
        }
        active += usize::from(item.active);
    }
    if active > MAX_ACTIVE_ITEMS {
        return Err(Error::new("Current inventory exceeds four active bindings"));
    }
    Ok(())
}

/// # Errors
/// Returns an error when the current inventory or exact item purchase violates the component or inventory rules.
pub fn plan_exact_item_purchase(
    graph: &ItemGraph,
    item: u64,
    state: &PurchaseState,
) -> Result<PurchasePlan> {
    let mut planner = PurchasePlanner::new(graph, state)?;
    planner.add_item_purchases(item, true, 0)?;
    Ok(planner.build_plan(state.liquid_souls))
}

/// Calculates remaining purchases from the current inventory and available souls.
///
/// # Errors
/// Returns an error when a purchase position, inventory, component path, or resulting core is invalid.
pub fn plan_purchases(
    graph: &ItemGraph,
    path: &[u64],
    core: &[u64],
    positions: &BTreeMap<u64, usize>,
    state: &PurchaseState,
) -> Result<PurchasePlan> {
    let mut planner = PurchasePlanner::new(graph, state)?;
    validate_purchase_positions(graph, path, positions, &state.owned)?;
    let mut selected = positions
        .iter()
        .map(|(item, position)| Ok((*position, graph.transitive_components(*item)?.len(), *item)))
        .collect::<Result<Vec<_>>>()?;
    selected.sort_unstable();
    let targets = resolve_route_targets(graph, path)?;
    let checkpoints = path.iter().zip(&targets).map(Some).chain([None]);
    for (index, checkpoint) in checkpoints.enumerate() {
        for (position, _, item) in &selected {
            if *position == index {
                planner.add_item_purchases(*item, false, 0)?;
            }
        }
        if let Some((item, target)) = checkpoint
            && !is_item_or_upgrade_owned(graph, *target, planner.state.owned())?
        {
            planner.add_item_purchases(*item, item != target, 0)?;
        }
    }
    for item in core {
        if !is_item_or_upgrade_owned(graph, *item, planner.state.owned())? {
            return Err(Error::new(
                "Purchase plan does not retain all required core items",
            ));
        }
    }
    Ok(planner.build_plan(state.liquid_souls))
}
