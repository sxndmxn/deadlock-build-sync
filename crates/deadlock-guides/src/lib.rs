#![forbid(unsafe_code)]
#![deny(warnings)]

mod ability_definition;
mod ability_grants;
mod ability_order;
mod ability_path;
mod ability_reconstruction;
mod ability_timeline;
mod artifact_bundle;
mod automatic_branch;
mod beam_display;
mod branch_diagnostics;
mod build_description;
mod build_selection;
mod build_support;
mod build_tags;
mod build_title;
mod bundle_evidence;
mod component_plan;
mod component_schedule;
mod context_actions;
mod context_analytics;
mod context_fingerprints;
mod context_generation;
mod context_items;
mod context_mechanics;
mod context_validation;
mod core_alternative;
mod core_evidence;
mod decision_route;
mod decision_state;
mod discovery_evidence;
mod duration_profile;
mod evidence_catalog;
mod evidence_catalog_groups;
mod evidence_catalog_header;
mod evidence_values;
mod frozen_pool;
mod generator_evidence;
mod guide_category;
mod guide_groups;
mod guide_item;
mod guide_presentation;
mod guide_reconstruction;
mod hero_cohort;
mod hero_evidence;
mod identity;
mod inventory;
mod item_evidence;
mod item_evidence_content;
mod item_evidence_validation;
mod mechanic_affinity;
mod mechanic_decisions;
mod mechanic_patterns;
mod mechanic_properties;
mod mechanic_responses;
mod narrative_catalog;
mod narrative_description;
mod narrative_generation;
mod policy_abstentions;
mod policy_alternatives;
mod policy_artifact;
mod policy_cards;
mod policy_claim;
mod policy_claim_generation;
mod policy_evaluation;
mod policy_generation;
mod policy_graph_generation;
mod policy_guard;
mod policy_model;
mod policy_node;
mod policy_projection;
mod policy_situational;
mod policy_state;
mod policy_validation;
mod presentation;
mod presentation_output;
mod projection_items;
mod projection_layout;
mod purchase_categories;
mod purchase_decisions;
mod purchase_effect_rules;
mod purchase_guidance;
mod purchase_guidance_types;
mod purchase_guide;
mod purchase_instructions;
mod purchase_markdown;
mod purchase_plan_types;
mod purchase_planner;
mod purchase_purposes;
mod purchase_route;
mod purchase_timing;
mod purchase_windows;
mod quality_evaluation;
mod quality_inputs;
mod quality_replay;
mod quality_report;
mod recommendation;
mod recommendation_guide;
mod recommendation_markdown;
mod recommendation_policy;
mod recommendation_types;
mod recommendation_validation;
mod selected_build;
mod selection_paths;
mod selection_tiers;
mod sequence_evidence;
mod situational_branch;
mod situational_evidence;
mod threat;
mod tier_evidence;
mod variant_categories;
mod variant_items;

pub use ability_definition::{
    AbilityDefinition, DEFAULT_ABILITY_UPGRADE_COSTS, parse_ability_definitions, validate_imbue,
};
pub use ability_order::select_ability_path;
pub use ability_path::AbilityPath;
pub use ability_timeline::{
    AbilityAction, AbilityCurrency, AbilityTimelineStep, schedule_ability_path,
    validate_ability_timeline,
};
pub use artifact_bundle::{
    ArtifactGuideBundle, load_artifact_guide_bundle, reconstruct_artifact_bundle,
};
pub use automatic_branch::{
    AutomaticBranch, AutomaticCondition, BranchTrigger, parse_automatic_branches,
};
pub use beam_display::{
    attach_beam_ability_names, generator_metadata, variant_state_labels, variant_statistics,
};
pub use build_selection::select_hero_build;
pub use build_support::{OutcomeEvidence, SUPPORT, SupportPolicy};
pub use build_tags::{BuildTagSelection, select_build_tags};
pub use build_title::{MAX_BUILD_NAME_CHARACTERS, format_build_name};
pub use component_schedule::{PurchasePriorities, schedule_component_path};
pub use context_fingerprints::{
    CONTEXT_SCHEMA_VERSION, KIT_BASIS_SCHEMA_VERSION, NARRATIVE_BASIS_SCHEMA_VERSION,
    calculate_context_sha256, calculate_kit_basis_sha256, calculate_narrative_basis_sha256,
    calculate_source_context_sha256,
};
pub use context_generation::{
    HeroContextInputs, build_hero_strategy_context, build_strategy_context_document,
};
pub use context_mechanics::{build_item_mechanics_catalog, calculate_item_mechanics_sha256};
pub use context_validation::StrategyContext;
pub use core_alternative::{CoreAlternativeContent, CoreAlternativeEvidence};
pub use core_evidence::{CorePolicyContent, CorePolicyEvidence};
pub use decision_state::{
    DECISION_STATE_SCHEMA_VERSION, DecisionInventory, DecisionState, DecisionStateContent,
    MatchEconomy,
};
pub use discovery_evidence::{
    REFRESH_INSTRUCTION, exclusion_reason, frozen_windows, validate_discovery,
};
pub use duration_profile::{
    DurationDistribution, DurationPopulation, summarize_duration_distribution,
    summarize_ending_duration_profile,
};
pub use evidence_catalog::{BuildEvidenceCatalog, BuildEvidenceIdentity};
pub use evidence_catalog_header::{
    BUILD_EVIDENCE_SCHEMA_VERSION, BuildEvidenceMetadata, BuildGenerator, CURRENT_METHOD_VERSION,
    expected_selection_method,
};
pub use frozen_pool::validate_frozen_pool;
pub use generator_evidence::{
    BEAM_METHOD_VERSION, BEAM_SCHEMA_VERSION, GeneratorEvidence, beam_generator_record,
    validate_generator_group, validate_generator_header, validate_generator_state,
};
pub use guide_category::{
    CORE_CATEGORY_DESCRIPTION, GuideCategory, MAX_CATEGORY_DESCRIPTION_BYTES,
    OPTIONAL_CORE_CATEGORY_DESCRIPTION, standard_category_description,
};
pub use guide_groups::{
    GuideGroupIndex, VARIANT_RULE, build_group_record, build_variant_record,
    describe_variant_changes, group_guides,
};
pub use guide_item::{
    GuideItem, MAX_ITEM_ANNOTATION_BYTES, conditional_item_annotation, format_integer,
    format_purchase_window,
};
pub use guide_presentation::build_presentation;
pub use guide_reconstruction::reconstruct_guide;
pub use hero_cohort::{HeroCohort, HeroCohortContent, RankExpansion, calculate_rank_cutoffs};
pub use hero_evidence::{HeroBuildEvidence, HeroEvidence};
pub use identity::GuideIdentity;
pub use inventory::{
    BASE_INVENTORY_SLOTS, InventoryState, MAX_ACTIVE_ITEMS, MAX_FLEX_SLOTS, purchase_item,
    sell_item,
};
pub use item_evidence::{ItemEvidence, nondecreasing_window_schedule};
pub use item_evidence_content::ItemEvidenceContent;
pub use mechanic_affinity::{MECHANIC_TAGS, asset_mechanics_refs, hero_item_affinity_scores};
pub use mechanic_decisions::{ConditionalItemDecision, conditional_item_decision};
pub use mechanic_responses::{
    classify_item_threat_responses, classify_observed_item_threats,
    classify_response_mechanic_labels,
};
pub use narrative_catalog::{
    NARRATIVE_GENERATOR_VERSION, NARRATIVE_SCHEMA_VERSION, NarrativeCatalog, NarrativeEntry,
};
pub use narrative_description::{
    MAXIMUM_BUILD_DESCRIPTION_CHARACTERS, MINIMUM_BUILD_DESCRIPTION_CHARACTERS,
    build_deterministic_description,
};
pub use narrative_generation::{
    NarrativeGeneration, generate_deterministic_narrative, generate_narrative_document,
};
pub use policy_artifact::{POLICY_ARTIFACT_SCHEMA_VERSION, PolicyArtifact};
pub use policy_cards::{CoreAlternativeCard, CounterCard, SpikeCard};
pub use policy_claim::{ClaimClass, EvidenceClaim};
pub use policy_evaluation::{EvaluationState, PolicyDecision, next_policy_decision};
pub use policy_generation::{PolicyInputs, generate_policy};
pub use policy_guard::{BranchCondition, DefaultCondition, Guard, GuardOperator, PolicyBranch};
pub use policy_model::{Abstention, AbstentionReason, BuildPolicy, BuildPolicyContent};
pub use policy_node::{NodeKind, PolicyNode};
pub use policy_projection::{ProjectionIdentity, project_policy_to_guide, projection_fingerprint};
pub use policy_state::ValidationContext;
pub use policy_validation::validate_policy;
pub use presentation::{
    BuildPresentation, LEGACY_MANAGED_MARKER, MANAGED_MARKER, PresentationAbilities,
    PresentationCategory, PresentationContent, PresentationItem,
};
pub use presentation_output::{render_presentation_markdown, serialize_presentation};
pub use projection_items::validate_optional_annotation;
pub use purchase_categories::build_purchase_categories;
pub use purchase_decisions::build_checkpoint_decisions;
pub use purchase_guidance::build_purchase_guidance;
pub use purchase_guidance_types::{
    ItemPurpose, PurchaseChoice, PurchaseDecision, PurchaseGuidance,
};
pub use purchase_guide::{PurchaseGuide, TacticalProfile};
pub use purchase_instructions::{format_choice_instruction, split_guidance};
pub use purchase_markdown::render_purchase_markdown;
pub use purchase_plan_types::{PurchasePlan, PurchaseState, PurchaseStep};
pub use purchase_planner::{plan_exact_item_purchase, plan_purchases};
pub use purchase_purposes::{
    classify_item_purpose, extract_description_text, extract_important_statistics,
    extract_primary_effect_text,
};
pub use purchase_route::{
    find_first_incomplete_checkpoint, is_item_or_upgrade_owned, resolve_route_targets,
    validate_purchase_positions,
};
pub use purchase_timing::{PurchaseTiming, parse_purchase_timing};
pub use purchase_windows::{
    GroupedPurchaseBucket, PURCHASE_BUCKET_INCREMENTS, PurchaseBucketRow, PurchaseWindow,
    analyze_purchase_windows, calculate_tier_horizons, choose_adaptive_bucket_increment,
    compute_average_bucket_matches, group_purchase_buckets, select_purchase_windows,
    wilson_score_interval,
};
pub use quality_evaluation::evaluate_policy;
pub use quality_inputs::QualityInputs;
pub use quality_replay::{ReplayCase, parse_replay};
pub use quality_report::build_quality_report;
pub use recommendation::recommend;
pub use recommendation_markdown::render_recommendation_markdown;
pub use recommendation_types::{Recommendation, RecommendationAction};
pub use selected_build::SelectedHeroBuild;
pub use sequence_evidence::{
    SequenceLevel, SequencePolicy, SequencePolicyContent, SequenceProduction, SequenceTransition,
};
pub use situational_branch::{SituationalBranch, SituationalBranchContent};
pub use situational_evidence::SituationalPolicy;
pub use threat::{EnemyScope, THREAT_CLASSES, Threat};
pub use tier_evidence::TierPolicyEvidence;
pub use variant_categories::validate_group_categories;
