use deadlock_data::{Error, Result};
use deadlock_input::ItemGraph;
use serde_json::{Value, json};

use crate::build_selection::select_hero_build;
use crate::decision_route::{SelectedPurchaseRoute, purchase_state, select_purchase_route};
use crate::decision_state::DecisionStateContent;
use crate::hero_evidence::HeroBuildEvidence;
use crate::policy_model::BuildPolicy;
use crate::purchase_guidance::build_purchase_guidance;
use crate::purchase_guidance_types::PurchaseGuidance;
use crate::purchase_instructions::format_choice_instruction;
use crate::purchase_plan_types::{PurchasePlan, PurchaseState};
use crate::purchase_planner::plan_purchases;
use crate::recommendation_types::{Recommendation, RecommendationAction};

pub fn recommend_guide(
    evidence: &HeroBuildEvidence,
    policy: &BuildPolicy,
    state: &DecisionStateContent,
    assets: &[Value],
) -> Result<Recommendation> {
    if state
        .path_id
        .as_ref()
        .is_some_and(|path| path != &evidence.path_id)
        || policy.content().path_id != evidence.path_id
    {
        return Err(Error::new(
            "Decision state and policy use different build identities",
        ));
    }
    let guidance = build_purchase_guidance(&select_hero_build(evidence, assets)?, assets)?;
    let graph = ItemGraph::from_assets(assets)?;
    let route = select_purchase_route(&guidance, state, &graph)?;
    let current = purchase_state(state);
    let plan = plan_purchases(&graph, &route.path, &route.core, &route.positions, &current)?;
    let first = plan.actions.first();
    let action = if first.is_none() {
        RecommendationAction::End
    } else if plan.save_souls.is_some_and(|souls| souls > 0) {
        RecommendationAction::Save
    } else {
        RecommendationAction::Buy
    };
    let details = json!({"schema_version":2,"core":route.core,"applied_branch":route.branch,"path_id":evidence.path_id,
        "next_purchase":first,"cash_shortfall":plan.save_souls,"remaining_route":plan.actions,"remaining_cost":plan.remaining_cost,
        "final_inventory":plan.final_inventory,"selected_placements":route.positions,
        "available_choices":available_choices(&guidance, &route, &current, &graph, &plan)?,
        "relative_wealth":state.economy.as_ref().map(|economy| economy.relative_wealth(state.clock_s)).transpose()?.flatten()});
    Ok(Recommendation {
        action,
        hero_id: state.hero_id,
        policy_id: policy.policy_id().into(),
        item_id: first.map(|step| step.item_id),
        target_item_id: first.map(|step| step.item_id),
        incremental_cost: Some(first.map_or(0, |step| step.incremental_cost)),
        reason: route.source.into(),
        purchase_plan: Some(details),
        ..Recommendation::default()
    })
}

fn available_choices(
    guidance: &PurchaseGuidance,
    route: &SelectedPurchaseRoute,
    state: &PurchaseState,
    graph: &ItemGraph,
    baseline: &PurchasePlan,
) -> Result<Vec<Value>> {
    let mut choices = Vec::new();
    for card in &guidance.choices {
        let mut current = serde_json::to_value(card)?;
        current["instruction"] = format_choice_instruction(guidance, card)?.into();
        current["current_plan"] = Value::Null;
        current["current_blocked_reason"] = Value::Null;
        current["extra_remaining_cost"] = Value::Null;
        if let Some(position) = route
            .positions
            .get(&card.item_id)
            .copied()
            .or(card.after_step)
        {
            let mut positions = route.positions.clone();
            positions.insert(card.item_id, position);
            match plan_purchases(graph, &route.path, &route.core, &positions, state) {
                Ok(plan) => {
                    current["extra_remaining_cost"] = serde_json::to_value(
                        i128::from(plan.remaining_cost) - i128::from(baseline.remaining_cost),
                    )?;
                    current["current_plan"] = serde_json::to_value(plan)?;
                }
                Err(error) => current["current_blocked_reason"] = error.to_string().into(),
            }
        }
        choices.push(current);
    }
    Ok(choices)
}
