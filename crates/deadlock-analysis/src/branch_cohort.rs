use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Result, integer};
use deadlock_guides::{PurchaseState, plan_purchases};
use deadlock_input::ItemGraph;
use serde_json::Value;

use crate::branch_candidates::conditions;
use crate::discovery_models::item_ids;

#[derive(Debug)]
pub struct ChoiceCohort {
    conditions: BTreeMap<(String, String), Vec<usize>>,
}

impl ChoiceCohort {
    pub fn new(rows: &[Value], indices: &[usize]) -> Self {
        let mut index = BTreeMap::<_, Vec<_>>::new();
        for position in indices {
            for (condition, value) in conditions(&rows[*position]) {
                index
                    .entry((condition, value.to_string()))
                    .or_default()
                    .push(*position);
            }
        }
        Self { conditions: index }
    }

    pub fn select(
        &self,
        rows: &[Value],
        candidate: &Value,
        graph: &ItemGraph,
    ) -> Result<Vec<usize>> {
        let key = (
            deadlock_data::text(candidate, "condition")?.to_owned(),
            candidate["value"].to_string(),
        );
        let mut legal = BTreeMap::new();
        let mut seen = BTreeSet::new();
        let mut selected = Vec::new();
        for position in self.conditions.get(&key).into_iter().flatten() {
            let row = &rows[*position];
            if !legal_substitution(row, candidate, graph, &mut legal)? {
                continue;
            }
            if seen.insert((integer(row, "match_id")?, integer(row, "player_slot")?)) {
                selected.push(*position);
            }
        }
        Ok(selected)
    }
}

fn legal_substitution(
    row: &Value,
    candidate: &Value,
    graph: &ItemGraph,
    cache: &mut BTreeMap<Vec<u64>, bool>,
) -> Result<bool> {
    if !candidate["substitution"].is_object() {
        return Ok(true);
    }
    let owned = item_ids(&row["owned_before"])?;
    if let Some(legal) = cache.get(&owned) {
        return Ok(*legal);
    }
    let substitution = &candidate["substitution"];
    let state = PurchaseState {
        owned: owned.clone(),
        ..PurchaseState::default()
    };
    let legal = plan_purchases(
        graph,
        &item_ids(&substitution["path"])?,
        &item_ids(&substitution["core"])?,
        &BTreeMap::new(),
        &state,
    )
    .is_ok();
    cache.insert(owned, legal);
    Ok(legal)
}
