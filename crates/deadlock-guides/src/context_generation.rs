use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{ArtifactCoverage, FingerprintLayers, Result, SnapshotManifest};
use deadlock_input::{HeroDurationStat, Patch};
use serde_json::{Map, Value, json};

use crate::ability_timeline::AbilityTimelineStep;
use crate::context_actions::describe_policy_actions;
use crate::context_analytics::{describe_ability_policy, ending_duration_evidence};
use crate::context_fingerprints::{
    CONTEXT_SCHEMA_VERSION, calculate_context_sha256, calculate_kit_basis_sha256,
    calculate_narrative_basis_sha256, calculate_source_context_sha256,
};
use crate::context_items::{core_context, strategy_tiers};
use crate::context_mechanics::{build_item_mechanics_catalog, calculate_item_mechanics_sha256};
use crate::context_validation::StrategyContext;
use crate::duration_profile::DurationDistribution;
use crate::policy_model::BuildPolicy;
use crate::purchase_guide::PurchaseGuide;

#[derive(Debug)]
pub struct HeroContextInputs<'input> {
    pub guide: &'input PurchaseGuide,
    pub kit: &'input Value,
    pub timeline: &'input [AbilityTimelineStep],
    pub duration: &'input [HeroDurationStat],
    pub distribution: Option<&'input DurationDistribution>,
    pub policy: Option<&'input BuildPolicy>,
    pub projection: Option<&'input PurchaseGuide>,
    pub matchups: Option<&'input Value>,
}

/// # Errors
/// Returns an error when mechanics, ability support, evidence references, or fingerprints cannot produce a complete context.
pub fn build_hero_strategy_context(
    inputs: &HeroContextInputs<'_>,
    assets: &[Value],
) -> Result<Value> {
    let guide = inputs.guide;
    let indexed = assets
        .iter()
        .filter_map(|asset| asset["id"].as_u64().map(|id| (id, asset)))
        .collect::<BTreeMap<_, _>>();
    let item_ids = guide
        .tiers
        .values()
        .flatten()
        .chain(&guide.core_items)
        .chain(&guide.optional_core_items)
        .map(|item| item.item_id)
        .collect::<BTreeSet<_>>();
    let catalog = build_item_mechanics_catalog(assets, &item_ids)?;
    let item_ids = item_ids.into_iter().collect::<Vec<_>>();
    let item_sha = calculate_item_mechanics_sha256(&item_ids, &catalog)?;
    let projected = inputs.projection.unwrap_or(guide);
    let projection = projection_context(projected)?;
    let mut context = json!({
        "hero_id":guide.hero_id,"hero":guide.hero_name,"path_id":guide.path_id,"path_label":guide.path_label,
        "snapshot_id":guide.snapshot_id,"policy_id":guide.policy_id,"hero_mechanics":inputs.kit,
        "item_mechanics_ids":item_ids,"item_mechanics_sha256":item_sha,
        "ability_policy":describe_ability_policy(guide, inputs.kit, inputs.timeline)?,
        "ending_duration_profile":ending_duration_evidence(inputs.duration, inputs.distribution)?,
        "core":core_context(guide)?,"tiers":strategy_tiers(guide, &indexed),
        "matchups":inputs.matchups.cloned().unwrap_or_else(|| json!({"same_lane":[],"whole_enemy_team":[]})),
        "policy":inputs.policy.map(|policy| policy.to_document(true)).transpose()?,
        "explainable_actions":describe_policy_actions(inputs.policy, &indexed)?,"projection":projection,
        "purchase_guidance":projected.purchase_guidance,
        "interpretation_constraints":INTERPRETATION_CONSTRAINTS,
    });
    let fingerprints = FingerprintLayers::calculate(
        &json!({"hero":inputs.kit,"items_sha256":item_sha}),
        &json!({"ability_policy":context["ability_policy"],"ending_duration_profile":context["ending_duration_profile"],
            "core":context["core"],"tiers":context["tiers"],"matchups":context["matchups"]}),
        &context["policy"],
        &json!({"interpretation_constraints":context["interpretation_constraints"]}),
        &projection,
    )?;
    context["fingerprints"] = serde_json::to_value(fingerprints)?;
    context["kit_basis_sha256"] = calculate_kit_basis_sha256(&context)?.into();
    context["narrative_basis_sha256"] = calculate_narrative_basis_sha256(&context)?.into();
    context["context_sha256"] = calculate_context_sha256(&context)?.into();
    Ok(context)
}

fn projection_context(guide: &PurchaseGuide) -> Result<Value> {
    Ok(
        json!({"build":{"path_id":guide.path_id,"path_label":guide.path_label,"archetype":guide.build_archetype,
        "tag_ids":guide.build_tag_ids,"tag_classes":guide.build_tag_classes,"tag_labels":guide.build_tag_labels,
        "tag_catalog_sha256":guide.build_tag_catalog_sha256},"guide_version":3,
        "categories":guide.rendered_categories()?.iter().map(crate::guide_category::GuideCategory::record).collect::<Vec<_>>(),
        "semantics":"CORE steps are the validated component path in automatic Queue. OPTIONAL, PICK ONE, UPGRADE, and ITEM POOL rows are optional. Core substitutions require separate core and branch admission."}),
    )
}

const INTERPRETATION_CONSTRAINTS: [&str; 8] = [
    "Tier membership uses first-ownership adoption. Display order uses observed net-worth timing, not outcome rate.",
    "Observed adopter outcomes and ending-duration profiles are descriptive associations. They do not establish item effects or live power curves.",
    "Ability actions use reached-state support and exact legal levels. Price tiers are not ability quarters.",
    "Explain only policy branches with supplied mechanics and observable states.",
    "Only validated CORE component steps enter automatic Queue. All choice and ITEM POOL rows remain optional.",
    "Cross-fitted doubly robust comparisons depend on assumptions. They do not prove that an item causes wins.",
    "Use VS, WHY, SWAP, WHEN, and SKIP lines for conditional item cards. Support each line with both item mechanics. Do not state an outcome effect.",
    "Do not invent mechanics, numeric effects, threats, combinations, or matchups absent from this context.",
];

/// # Errors
/// Returns an error when the completed context fails snapshot, coverage, mechanics, or fingerprint validation.
pub fn build_strategy_context_document(
    patch: &Patch,
    contexts: Vec<Value>,
    manifest: &SnapshotManifest,
    item_mechanics: Map<String, Value>,
    coverage: &ArtifactCoverage,
) -> Result<StrategyContext> {
    let content = manifest.content();
    let mut document = Value::Object(coverage.document_fields());
    document["schema_version"] = CONTEXT_SCHEMA_VERSION.into();
    document["snapshot_manifest"] = manifest.to_document()?;
    document["patch"] = patch.to_document()?.into();
    document["filters"] = json!({"game_mode":content.game_mode,"match_mode":content.match_mode,"rank_range":content.rank_range,
        "as_of_timestamp":content.as_of_timestamp,"client_version":content.client_version,"epochs":content.epochs,
        "outcome_policy":content.outcome_policy,"minimum_decision_support":1,"low_decision_support_warning_threshold":20});
    document["item_mechanics"] = item_mechanics.into();
    document["heroes"] = contexts.into();
    document["source_context_sha256"] = calculate_source_context_sha256(&document)?.into();
    StrategyContext::from_document(document)
}
