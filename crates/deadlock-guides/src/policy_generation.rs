use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Error, Result, SnapshotManifest, text};
use deadlock_input::{HeroDurationStat, ItemGraph};
use serde_json::Value;

use crate::ability_definition::parse_ability_definitions;
use crate::ability_timeline::AbilityTimelineStep;
use crate::policy_abstentions::build_abstentions;
use crate::policy_alternatives::build_core_alternative_cards;
use crate::policy_claim_generation::ClaimContext;
use crate::policy_graph_generation::{ability_nodes, purchase_graph};
use crate::policy_model::{BuildPolicy, BuildPolicyContent};
use crate::policy_situational::{SituationalPolicyEntry, build_situational_entry};
use crate::policy_state::ValidationContext;
use crate::policy_validation::validate_policy;
use crate::purchase_guide::PurchaseGuide;
use crate::situational_evidence::SituationalPolicy;

#[derive(Debug)]
pub struct PolicyInputs<'input> {
    pub guide: &'input PurchaseGuide,
    pub kit: &'input Value,
    pub timeline: &'input [AbilityTimelineStep],
    pub duration: &'input [HeroDurationStat],
    pub situational: Option<&'input SituationalPolicy>,
}

/// # Errors
/// Returns an error when the selected build lacks supported mechanics, references, ability data, or a legal purchase graph.
pub fn generate_policy(
    inputs: &PolicyInputs<'_>,
    assets: &[Value],
    manifest: &SnapshotManifest,
) -> Result<(BuildPolicy, ValidationContext)> {
    let guide = inputs.guide;
    if !(3..=9).contains(&guide.core_items.len()) {
        return Err(Error::new("Guide does not have a supported core size"));
    }
    let validation = ValidationContext {
        item_graph: ItemGraph::from_assets(assets)?,
        ability_definitions: parse_ability_definitions(inputs.kit)?,
        level_info: inputs.kit["level_info"].clone(),
        learned_abilities: BTreeSet::new(),
    };
    let mut context = ClaimContext {
        manifest,
        cohort: manifest.cohort_record()?,
    };
    if let Some(cohort) = &guide.cohort {
        context
            .cohort
            .insert("rank_range".into(), cohort.rank_range()?.to_document());
    }
    let mut evidence = context.base_evidence(guide, &validation.ability_definitions)?;
    let situational = situational_entries(inputs, assets, &context)?;
    evidence.extend(
        situational
            .iter()
            .map(|entry| (entry.claim.claim_id.clone(), entry.claim.clone())),
    );
    let (alternatives, claims) = build_core_alternative_cards(guide, &context)?;
    evidence.extend(
        claims
            .into_iter()
            .map(|claim| (claim.claim_id.clone(), claim)),
    );
    let (entry, nodes) = purchase_graph(guide, &context.core_claim(guide)?.claim_id, &situational)?;
    let policy = BuildPolicy::new(BuildPolicyContent {
        schema_version: 5,
        hero_id: guide.hero_id,
        variant: "state-aware-multi-path-v5".into(),
        invariant_kit_id: text(inputs.kit, "mechanics_sha256")?.into(),
        strategic_role: inputs.kit["description"]["role"]
            .as_str()
            .unwrap_or("evidence-grounded default")
            .into(),
        snapshot_id: manifest.identifier().into(),
        entry,
        nodes,
        evidence: evidence.into_values().collect(),
        ability_plan: ability_nodes(guide, inputs.timeline)?,
        abstentions: build_abstentions(guide, inputs.duration, inputs.situational)?,
        counter_cards: situational.into_iter().map(|entry| entry.card).collect(),
        core_alternatives: alternatives,
        path_id: guide.path_id.clone(),
        path_label: guide.path_label.clone(),
    })?;
    validate_policy(&policy, &validation)?;
    Ok((policy, validation))
}

fn situational_entries(
    inputs: &PolicyInputs<'_>,
    assets: &[Value],
    context: &ClaimContext<'_>,
) -> Result<Vec<SituationalPolicyEntry>> {
    let assets = assets
        .iter()
        .filter_map(|asset| asset["id"].as_u64().map(|id| (id, asset)))
        .collect::<BTreeMap<_, _>>();
    let mut entries = Vec::new();
    for (index, branch) in inputs
        .situational
        .into_iter()
        .flat_map(SituationalPolicy::branches)
        .enumerate()
    {
        let branch = branch.content();
        if inputs
            .guide
            .core_items
            .iter()
            .any(|item| item.item_id == branch.item_id)
        {
            return Err(Error::new("Situational item repeats a core item"));
        }
        entries.push(build_situational_entry(
            index + 1,
            inputs.guide.hero_id,
            branch,
            &assets,
            context,
        )?);
    }
    Ok(entries)
}
