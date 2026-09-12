use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::Result;
use deadlock_guides::{PurchaseState, plan_exact_item_purchase};
use deadlock_input::ItemGraph;
use serde::{Deserialize, Serialize};

use crate::beam_model::BeamModel;
use crate::beam_support::{BeamOwnership, CoreGroups, assign_core_group};

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct BeamRoute {
    pub core: Vec<u64>,
    pub targets: Vec<u64>,
    pub path: Vec<u64>,
    pub score: f64,
    pub spent: u64,
    pub net_worth: u64,
    pub cash: u64,
    pub owners: u64,
}

impl Default for BeamRoute {
    fn default() -> Self {
        Self {
            core: Vec::new(),
            targets: Vec::new(),
            path: Vec::new(),
            score: 0.0,
            spent: 0,
            net_worth: 800,
            cash: 800,
            owners: 0,
        }
    }
}

#[derive(Debug)]
pub struct SearchRequest<'a> {
    pub graph: &'a ItemGraph,
    pub model: &'a BeamModel,
    pub ownership: &'a BeamOwnership,
    pub groups: &'a CoreGroups,
    pub group: &'a str,
    pub state: u8,
    pub candidates: &'a [u64],
}

#[derive(Debug)]
pub struct SearchResult {
    pub routes: Vec<BeamRoute>,
    pub expansions: u64,
    pub unassigned: u64,
}

fn extend_route(
    request: &SearchRequest<'_>,
    route: &BeamRoute,
    item: u64,
) -> Result<Option<BeamRoute>> {
    if route.targets.contains(&item) || route.core.contains(&item) {
        return Ok(None);
    }
    let state = PurchaseState {
        owned: route.core.clone(),
        ..PurchaseState::default()
    };
    let Ok(plan) = plan_exact_item_purchase(request.graph, item, &state) else {
        return Ok(None);
    };
    let spent = route.spent + plan.remaining_cost;
    if spent > 19200 || plan.final_inventory.len() > 6 {
        return Ok(None);
    }
    let mut child = route.clone();
    child.spent = spent;
    child.targets.push(item);
    child.core = plan.final_inventory;
    child.core.sort_unstable();
    for step in plan.actions {
        child.net_worth += step.incremental_cost.saturating_sub(child.cash);
        child.cash = child.cash.saturating_sub(step.incremental_cost);
        let Some(value) = request.model.score(
            child.net_worth,
            request.state,
            step.item_id,
            step.incremental_cost,
            child.path.len(),
        )?
        else {
            return Ok(None);
        };
        child.score += value;
        child.path.push(step.item_id);
    }
    Ok(Some(child))
}

pub fn search_group(request: &SearchRequest<'_>) -> Result<SearchResult> {
    let maximum_depth = 6 * request
        .candidates
        .iter()
        .map(|item| {
            request
                .graph
                .transitive_components(*item)
                .map(|items| items.len() + 1)
        })
        .collect::<Result<Vec<_>>>()?
        .into_iter()
        .max()
        .unwrap_or(1);
    let anchors = request.groups[request.group]
        .iter()
        .flat_map(|core| core.iter().copied())
        .collect::<BTreeSet<_>>();
    let minimum = if request.groups[request.group]
        .iter()
        .map(BTreeSet::len)
        .min()
        == Some(3)
    {
        3
    } else {
        4
    };
    let mut frontier = vec![BeamRoute::default()];
    let mut terminal = BTreeMap::new();
    let mut expansions = 0;
    let mut unassigned = 0;
    for _ in 0..maximum_depth {
        let mut following = BTreeMap::<(Vec<u64>, Vec<u64>), BeamRoute>::new();
        for route in &frontier {
            for item in request.candidates {
                if route.targets.is_empty() && !anchors.contains(item) {
                    continue;
                }
                expansions += 1;
                let Some(mut child) = extend_route(request, route, *item)? else {
                    continue;
                };
                if request.ownership.count(&child.core, true) < 200 {
                    continue;
                }
                let mut targets = child.targets.clone();
                targets.sort_unstable();
                let identity = (child.core.clone(), targets);
                if following.get(&identity).is_none_or(|previous| {
                    child.score > previous.score
                        || (child.score.total_cmp(&previous.score).is_eq()
                            && child.path < previous.path)
                }) {
                    following.insert(identity, child.clone());
                }
                if child.core.len() < minimum || request.ownership.count(&child.core, false) < 200 {
                    continue;
                }
                match assign_core_group(&child.core, request.groups)? {
                    Some(group) if group == request.group => {
                        child.owners = request.ownership.count(&child.core, false);
                        terminal.insert((child.core.clone(), child.path.clone()), child);
                    }
                    None => unassigned += 1,
                    Some(_) => {}
                }
            }
        }
        frontier = following.into_values().collect();
        frontier.sort_by(|left, right| {
            right
                .score
                .total_cmp(&left.score)
                .then_with(|| left.path.cmp(&right.path))
        });
        frontier.truncate(16);
        if frontier.is_empty() {
            break;
        }
    }
    let mut routes = terminal.into_values().collect::<Vec<_>>();
    routes.sort_by(|left, right| {
        right
            .score
            .total_cmp(&left.score)
            .then(right.owners.cmp(&left.owners))
            .then_with(|| left.core.cmp(&right.core))
            .then_with(|| left.path.cmp(&right.path))
    });
    Ok(SearchResult {
        routes,
        expansions,
        unassigned,
    })
}
