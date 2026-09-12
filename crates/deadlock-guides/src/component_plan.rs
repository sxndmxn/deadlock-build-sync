use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Error, Result};
use deadlock_input::ItemGraph;

use crate::inventory::{InventoryState, purchase_item};

#[derive(Debug, Default)]
pub struct ComponentPlan {
    pub item_ids: Vec<u64>,
    pub dependencies: Vec<BTreeSet<usize>>,
}

#[derive(Debug)]
struct ComponentPlanner<'graph> {
    graph: &'graph ItemGraph,
    plan: ComponentPlan,
    consumed_by: BTreeMap<usize, usize>,
    owned_actions: BTreeMap<u64, usize>,
    last_actions: BTreeMap<u64, usize>,
    state: InventoryState,
}

pub fn plan_component_actions(graph: &ItemGraph, targets: &[u64]) -> Result<ComponentPlan> {
    let mut planner = ComponentPlanner {
        graph,
        plan: ComponentPlan::default(),
        consumed_by: BTreeMap::new(),
        owned_actions: BTreeMap::new(),
        last_actions: BTreeMap::new(),
        state: InventoryState::default(),
    };
    let mut final_actions = Vec::new();
    for item_id in targets {
        let action = planner.plan(*item_id, 0)?;
        if final_actions.contains(&action) {
            return Err(Error::new(format!(
                "Final item was already scheduled: {item_id}"
            )));
        }
        if let Some(previous) = final_actions.last() {
            planner.plan.dependencies[action].insert(*previous);
        }
        final_actions.push(action);
    }
    if planner.state.owned().iter().collect::<BTreeSet<_>>() != targets.iter().collect() {
        return Err(Error::new(
            "Component path does not reach the specified final inventory",
        ));
    }
    Ok(planner.plan)
}

impl ComponentPlanner<'_> {
    fn plan(&mut self, item_id: u64, depth: usize) -> Result<usize> {
        if depth > 64 || self.plan.item_ids.len() >= 4096 {
            return Err(Error::new(
                "Component plan exceeds its depth or action limit",
            ));
        }
        if self.state.owned().contains(&item_id) {
            return self
                .owned_actions
                .get(&item_id)
                .copied()
                .ok_or_else(|| Error::new("Owned item has no planned purchase action"));
        }
        let components = self.graph.components(item_id)?.to_vec();
        let component_actions = components
            .iter()
            .map(|id| self.plan(*id, depth + 1))
            .collect::<Result<Vec<_>>>()?;
        let index = self.plan.item_ids.len();
        let dependencies = self.dependencies(item_id, &component_actions)?;
        if components.iter().any(|id| !self.state.owned().contains(id)) {
            return Err(Error::new(format!(
                "Planned item is missing an owned component: {item_id}"
            )));
        }
        self.state = purchase_item(self.graph, &self.state, item_id, 0)?;
        self.plan.item_ids.push(item_id);
        self.plan.dependencies.push(dependencies);
        for (component, action) in components.iter().zip(component_actions) {
            self.consumed_by.insert(action, index);
            self.owned_actions.remove(component);
        }
        self.owned_actions.insert(item_id, index);
        self.last_actions.insert(item_id, index);
        Ok(index)
    }

    fn dependencies(&self, item_id: u64, component_actions: &[usize]) -> Result<BTreeSet<usize>> {
        let mut result = component_actions.iter().copied().collect::<BTreeSet<_>>();
        if let Some(previous) = self.last_actions.get(&item_id) {
            let consumer = self.consumed_by.get(previous).ok_or_else(|| {
                Error::new(format!(
                    "Item {item_id} cannot be purchased again before its prior copy is consumed"
                ))
            })?;
            result.insert(*consumer);
        }
        Ok(result)
    }
}
