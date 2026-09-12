use std::cmp::Ordering;
use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Error, Result};
use deadlock_input::ItemGraph;

use crate::component_plan::{ComponentPlan, plan_component_actions};
use crate::inventory::{InventoryState, purchase_item};

pub type PurchasePriorities = BTreeMap<u64, (f64, f64, u64)>;

#[derive(Debug)]
struct ComponentScheduleSearch<'graph> {
    graph: &'graph ItemGraph,
    plan: ComponentPlan,
    targets: BTreeSet<u64>,
    priorities: &'graph PurchasePriorities,
    failed_states: BTreeSet<(BTreeSet<usize>, Vec<u64>)>,
}

/// Schedules component purchases with inventory limits and the specified final item order.
///
/// # Errors
/// Returns an error when no legal schedule reaches the final inventory.
pub fn schedule_component_path(
    graph: &ItemGraph,
    targets: &[u64],
    priorities: &PurchasePriorities,
) -> Result<Vec<u64>> {
    if targets.is_empty() || targets.iter().collect::<BTreeSet<_>>().len() != targets.len() {
        return Err(Error::new(
            "Component schedule requires distinct final inventory items",
        ));
    }
    if priorities
        .values()
        .any(|(first, second, _)| first.is_nan() || second.is_nan())
    {
        return Err(Error::new("Purchase priorities must not contain NaN"));
    }
    let plan = plan_component_actions(graph, targets)?;
    let mut search = ComponentScheduleSearch {
        graph,
        plan,
        targets: targets.iter().copied().collect(),
        priorities,
        failed_states: BTreeSet::new(),
    };
    search
        .search(&BTreeSet::new(), &InventoryState::default())?
        .ok_or_else(|| {
            Error::new("No legal chronological component schedule reaches the final inventory")
        })
}

impl ComponentScheduleSearch<'_> {
    fn ready_actions(&self, completed: &BTreeSet<usize>) -> Vec<usize> {
        let mut ready = self
            .plan
            .dependencies
            .iter()
            .enumerate()
            .filter(|(index, dependencies)| {
                !completed.contains(index) && dependencies.is_subset(completed)
            })
            .map(|(index, _)| index)
            .collect::<Vec<_>>();
        ready.sort_by(|left, right| self.compare_priorities(*left, *right));
        ready
    }

    fn compare_priorities(&self, left: usize, right: usize) -> Ordering {
        let priority = |index: usize| {
            let id = self.plan.item_ids[index];
            self.priorities
                .get(&id)
                .copied()
                .unwrap_or((f64::INFINITY, f64::INFINITY, id))
        };
        let left_priority = priority(left);
        let right_priority = priority(right);
        left_priority
            .0
            .total_cmp(&right_priority.0)
            .then_with(|| left_priority.1.total_cmp(&right_priority.1))
            .then_with(|| left_priority.2.cmp(&right_priority.2))
            .then(left.cmp(&right))
    }

    fn search(
        &mut self,
        completed: &BTreeSet<usize>,
        state: &InventoryState,
    ) -> Result<Option<Vec<u64>>> {
        if completed.len() == self.plan.item_ids.len() {
            return Ok(
                (state.owned().iter().copied().collect::<BTreeSet<_>>() == self.targets)
                    .then(Vec::new),
            );
        }
        let mut owned = state.owned().to_vec();
        owned.sort_unstable();
        let key = (completed.clone(), owned);
        if self.failed_states.contains(&key) {
            return Ok(None);
        }
        for action in self.ready_actions(completed) {
            let id = self.plan.item_ids[action];
            if self
                .graph
                .components(id)?
                .iter()
                .any(|component| !state.owned().contains(component))
            {
                continue;
            }
            let Ok(next_state) = purchase_item(self.graph, state, id, 0) else {
                continue;
            };
            let mut next_completed = completed.clone();
            next_completed.insert(action);
            if let Some(mut suffix) = self.search(&next_completed, &next_state)? {
                suffix.insert(0, id);
                return Ok(Some(suffix));
            }
        }
        self.failed_states.insert(key);
        Ok(None)
    }
}
