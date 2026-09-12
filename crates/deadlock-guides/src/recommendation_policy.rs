use std::collections::BTreeSet;

use deadlock_data::{Error, Result};
use deadlock_input::ItemGraph;
use serde_json::json;

use crate::decision_state::DecisionStateContent;
use crate::inventory::{InventoryState, purchase_item};
use crate::policy_evaluation::{EvaluationState, next_policy_decision};
use crate::policy_model::BuildPolicy;
use crate::policy_node::{NodeKind, PolicyNode};
use crate::recommendation_types::{Recommendation, RecommendationAction};

pub fn recommend_policy(
    policy: &BuildPolicy,
    state: &DecisionStateContent,
    graph: &ItemGraph,
    inventory: InventoryState,
    threats: &BTreeSet<String>,
) -> Result<Recommendation> {
    let required = policy
        .content()
        .nodes
        .iter()
        .filter(|node| node.kind == NodeKind::Purchase && !node.optional)
        .filter_map(|node| node.item_id)
        .collect::<BTreeSet<_>>();
    if !required.is_empty() && required.iter().all(|id| inventory.owned().contains(id)) {
        return Ok(end(
            policy,
            state,
            "Required policy purchases are currently owned",
        ));
    }
    let evaluation = evaluation_state(state, inventory, threats)?;
    let decision = next_policy_decision(policy, &evaluation)?;
    if let Some(abstention) = decision.abstention {
        return Ok(Recommendation::abstain(
            state.hero_id,
            policy.policy_id(),
            abstention.detail,
        ));
    }
    if decision.kind == Some(NodeKind::End) {
        return Ok(end(policy, state, "The typed policy graph is complete"));
    }
    if let Some(node_id) = decision.node_id {
        let node = policy
            .content()
            .nodes
            .iter()
            .find(|node| node.node_id == node_id)
            .ok_or_else(|| Error::new("Policy decision references an unknown node"))?;
        return recommend_node(policy, state, node, &evaluation.inventory, graph);
    }
    Ok(Recommendation::abstain(
        state.hero_id,
        policy.policy_id(),
        "The typed policy graph has no executable action".into(),
    ))
}

fn end(policy: &BuildPolicy, state: &DecisionStateContent, reason: &str) -> Recommendation {
    Recommendation {
        action: RecommendationAction::End,
        hero_id: state.hero_id,
        policy_id: policy.policy_id().into(),
        reason: reason.into(),
        ..Recommendation::default()
    }
}

fn evaluation_state(
    state: &DecisionStateContent,
    inventory: InventoryState,
    threats: &BTreeSet<String>,
) -> Result<EvaluationState> {
    let observable = json!({"enemy.heroes":state.enemy_hero_ids,"enemy.lane_heroes":state.lane_enemy_hero_ids,
        "enemy.threats":threats,"enemy.items":state.enemy_item_ids,"ally.heroes":state.allied_hero_ids,
        "inventory.items":state.inventory.items,"inventory.components":state.inventory.components,
        "inventory.open_slots":state.inventory.open_slots,"inventory.active_bindings":state.inventory.active_bindings,
        "inventory.flex_slots":state.inventory.flex_slots,"clock_s":state.clock_s,"economy.liquid":state.liquid_souls,
        "objectives.available":state.objectives,"objectives.flex_slots":state.inventory.flex_slots,
        "cohort.match_mode":state.match_mode,"cohort.rank_badge":state.average_badge});
    Ok(EvaluationState {
        observable: serde_json::from_value(observable)?,
        inventory,
        learned_abilities: state.learned_abilities.iter().copied().collect(),
        clock_s: state.clock_s,
    })
}

fn recommend_node(
    policy: &BuildPolicy,
    state: &DecisionStateContent,
    node: &PolicyNode,
    inventory: &InventoryState,
    graph: &ItemGraph,
) -> Result<Recommendation> {
    let Some(target) = node.item_id.filter(|_| node.kind == NodeKind::Purchase) else {
        return Ok(Recommendation::abstain(
            state.hero_id,
            policy.policy_id(),
            "The policy action is not a purchase".into(),
        ));
    };
    let Some(item_id) = first_missing(target, inventory, graph)?
        .filter(|id| purchase_item(graph, inventory, *id, 0).is_ok())
    else {
        return Ok(Recommendation::abstain(
            state.hero_id,
            policy.policy_id(),
            format!(
                "Policy purchase {} is illegal in the supplied state",
                node.node_id
            ),
        ));
    };
    let cost = graph.incremental_cash_cost(item_id, inventory.owned())?;
    let claim = policy
        .content()
        .evidence
        .iter()
        .find(|claim| Some(claim.claim_id.as_str()) == node.evidence_ref.as_deref());
    let cards = policy
        .content()
        .counter_cards
        .iter()
        .filter(|card| {
            Some(card.item_id) == node.item_id
                && Some(card.evidence_ref.as_str()) == node.evidence_ref.as_deref()
        })
        .collect::<Vec<_>>();
    if cards.len() > 1 {
        return Err(Error::new("Policy has ambiguous counter metadata"));
    }
    let counter = cards.first().map(serde_json::to_value).transpose()?;
    Ok(Recommendation {
        action: if state.liquid_souls >= cost {
            RecommendationAction::Buy
        } else {
            RecommendationAction::Save
        },
        hero_id: state.hero_id,
        policy_id: policy.policy_id().into(),
        item_id: Some(item_id),
        target_item_id: Some(target),
        incremental_cost: Some(cost),
        support: claim.map(|claim| claim.numerator.unwrap_or(claim.support)),
        support_share: claim
            .filter(|claim| claim.numerator.is_some())
            .and_then(|claim| claim.estimate),
        backoff_level: Some(
            if node.optional {
                "situational"
            } else {
                "policy"
            }
            .into(),
        ),
        reason: if node.annotation.is_empty() {
            "Deterministic typed policy graph.".into()
        } else {
            node.annotation.clone()
        },
        counter,
        purchase_plan: None,
    })
}

fn first_missing(
    target: u64,
    inventory: &InventoryState,
    graph: &ItemGraph,
) -> Result<Option<u64>> {
    let mut pending = vec![target];
    while let Some(id) = pending.pop() {
        if inventory.owned().contains(&id) {
            continue;
        }
        graph.require(id)?;
        if let Some(component) = graph
            .components(id)?
            .iter()
            .find(|id| !inventory.owned().contains(id))
        {
            pending.push(*component);
        } else {
            return Ok(Some(id));
        }
    }
    Ok(None)
}
