use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Error, Result};
use deadlock_input::ItemGraph;
use serde_json::Value;

use crate::automatic_branch::AutomaticBranch;
use crate::item_evidence::ItemEvidence;
use crate::purchase_decisions::build_checkpoint_decisions;
use crate::purchase_guidance_types::{PurchaseChoice, PurchaseGuidance};
use crate::purchase_plan_types::{PurchasePlan, PurchaseState};
use crate::purchase_planner::plan_purchases;
use crate::purchase_purposes::classify_item_purpose;
use crate::purchase_timing::PurchaseTiming;
use crate::selected_build::SelectedHeroBuild;

#[derive(Debug)]
struct GuidanceContext<'build> {
    build: &'build SelectedHeroBuild,
    graph: ItemGraph,
    assets: BTreeMap<u64, &'build Value>,
    path: Vec<u64>,
    core: Vec<u64>,
}

/// # Errors
/// Returns an error when the default path, item mechanics, or automatic branch differs from admitted evidence.
pub fn build_purchase_guidance(
    build: &SelectedHeroBuild,
    assets: &[Value],
) -> Result<PurchaseGuidance> {
    let context = GuidanceContext {
        build,
        graph: ItemGraph::from_assets(assets)?,
        assets: assets
            .iter()
            .filter_map(|asset| asset["id"].as_u64().map(|id| (id, asset)))
            .collect(),
        path: build
            .core_purchase_path
            .iter()
            .map(|item| item.content().item_id)
            .collect(),
        core: build
            .core
            .iter()
            .map(|item| item.content().item_id)
            .collect(),
    };
    let default = plan_purchases(
        &context.graph,
        &context.path,
        &context.core,
        &BTreeMap::new(),
        &PurchaseState::default(),
    )?;
    validate_default_plan(&context, &default)?;
    let timing = build
        .purchase_timing
        .iter()
        .map(|row| (row.item_id, row))
        .collect::<BTreeMap<_, _>>();
    let choices = build
        .tiers
        .values()
        .flatten()
        .map(|item| context.build_choice(item, timing.get(&item.content().item_id).copied()))
        .collect::<Result<Vec<_>>>()?;
    let mut decisions = Vec::new();
    for position in 0..=context.path.len() {
        decisions.extend(build_checkpoint_decisions(
            position,
            &choices,
            &context.graph,
        )?);
    }
    let automatic_branches = build
        .automatic_branches
        .iter()
        .map(|branch| context.build_automatic_branch(branch))
        .collect::<Result<Vec<_>>>()?;
    Ok(PurchaseGuidance {
        core_ids: context.core,
        default_path: default,
        choices,
        decisions,
        names: context
            .graph
            .nodes()
            .iter()
            .map(|(id, node)| (*id, node.name.clone()))
            .collect(),
        evidence_basis:
            "Admitted production core; optional effects and timing do not prove an outcome benefit"
                .into(),
        schema_version: 3,
        cohort: build.cohort.to_document()?,
        evidence: build.evidence_summary.clone(),
        automatic_branches,
    })
}

fn validate_default_plan(context: &GuidanceContext<'_>, plan: &PurchasePlan) -> Result<()> {
    if plan
        .actions
        .iter()
        .map(|step| step.item_id)
        .collect::<Vec<_>>()
        != context.path
        || plan
            .final_inventory
            .iter()
            .copied()
            .collect::<BTreeSet<_>>()
            != context.core.iter().copied().collect()
        || plan.remaining_cost != context.build.core_target_cost
    {
        return Err(Error::new(
            "Purchase guidance differs from the admitted default path",
        ));
    }
    Ok(())
}

impl GuidanceContext<'_> {
    fn build_choice(
        &self,
        item: &ItemEvidence,
        timing: Option<&PurchaseTiming>,
    ) -> Result<PurchaseChoice> {
        let item = item.content();
        let ancestors = self.graph.transitive_components(item.item_id)?;
        let upgrades = self
            .core
            .iter()
            .copied()
            .filter(|id| ancestors.contains(id))
            .collect::<Vec<_>>();
        let (position, timing_basis) = choice_position(&self.path, &upgrades, timing)?;
        let (plan, blocked_reason) =
            position.map_or((None, None), |position| {
                match plan_purchases(
                    &self.graph,
                    &self.path,
                    &self.core,
                    &BTreeMap::from([(item.item_id, position)]),
                    &PurchaseState::default(),
                ) {
                    Ok(plan) => (Some(plan), None),
                    Err(error) => (None, Some(error.to_string())),
                }
            });
        let rebought_components = plan.as_ref().map_or_else(Vec::new, repeated_components);
        let extra_path_cost = plan
            .as_ref()
            .map(|plan| i128::from(plan.remaining_cost) - i128::from(self.build.core_target_cost));
        let asset = self
            .assets
            .get(&item.item_id)
            .ok_or_else(|| Error::new("Purchase choice has no item asset"))?;
        Ok(PurchaseChoice {
            item_id: item.item_id,
            name: item.item.clone(),
            tier: u8::try_from(item.tier)?,
            catalog_cost: self.graph.require(item.item_id)?.cost,
            purpose: classify_item_purpose(asset)?,
            after_step: position,
            timing: timing.cloned(),
            timing_basis,
            route: ancestors.iter().copied().chain([item.item_id]).collect(),
            upgrades_core: upgrades,
            plan,
            blocked_reason,
            extra_path_cost,
            rebought_components,
        })
    }

    fn build_automatic_branch(&self, branch: &AutomaticBranch) -> Result<AutomaticBranch> {
        let path = if branch.substituted_path.is_empty() {
            &self.path
        } else {
            &branch.substituted_path
        };
        let core = if branch.substituted_core.is_empty() {
            &self.core
        } else {
            &branch.substituted_core
        };
        let mut branch = branch.clone();
        branch.default_plan = Some(plan_purchases(
            &self.graph,
            path,
            core,
            &BTreeMap::from([(branch.item_id, branch.after_step)]),
            &PurchaseState::default(),
        )?);
        Ok(branch)
    }
}

fn choice_position(
    path: &[u64],
    upgrades: &[u64],
    timing: Option<&PurchaseTiming>,
) -> Result<(Option<usize>, String)> {
    let position = timing.map(PurchaseTiming::position).transpose()?.flatten();
    let minimum = upgrades
        .iter()
        .filter_map(|id| {
            path.iter()
                .position(|item| item == id)
                .map(|index| index + 1)
        })
        .max()
        .unwrap_or(0);
    if position.is_some_and(|position| position < minimum) {
        return Ok((
            None,
            "Timing unknown; observed position precedes a required core item".into(),
        ));
    }
    let basis = if position.is_some() {
        "observed adjacent first-purchase anchors in the training build cohort"
    } else {
        "Timing unknown; adjacent purchase evidence is insufficient"
    };
    Ok((position, basis.into()))
}

fn repeated_components(plan: &PurchasePlan) -> Vec<u64> {
    let mut counts = BTreeMap::<u64, usize>::new();
    for action in &plan.actions {
        *counts.entry(action.item_id).or_default() += 1;
    }
    let mut seen = BTreeSet::new();
    plan.actions
        .iter()
        .map(|action| action.item_id)
        .filter(|id| counts[id] > 1 && seen.insert(*id))
        .collect()
}
