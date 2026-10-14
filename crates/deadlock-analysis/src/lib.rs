#![forbid(unsafe_code)]
#![deny(warnings)]

mod build_assembly;
mod build_evaluation;
mod build_variants;
mod counter_items;
mod experiments;

pub use counter_items::GroupInteraction;
mod database;
mod extraction;
mod hero_build_production;
mod item_effects;
mod item_imbues;
mod item_statistics;
mod refresh;
mod refresh_configuration;
mod ridge_logistic;
mod run_inputs;
mod sources;
mod sql_resources;

pub use build_assembly::{DEFAULT_SCORING, ItemScoring};
pub use experiments::{
    AgreementPair, BuildStability, ConditionResult, CounterResult, EffectModel, FractionResult,
    Interaction, ItemEffectRow, LabelHalves, LandmarkAgreement, ModelResult, PlaceboResult,
    ScoringResult, WindowEvidence, compare_effect_models, compare_item_scoring,
    compare_scoring_by_landmark, compare_scoring_pair, compare_situational_signal,
    compare_training_fractions, compare_variant_agreement, estimate_counter_interactions,
    estimate_enemy_item_counters, estimate_split_item_effects, measure_build_stability,
    measure_counter_placebo, measure_counter_windows, measure_label_halves, measure_pair_placebo,
};
pub use hero_build_production::produce_hero_builds;
pub use item_effects::{DEFAULT_PENALTIES, EffectPenalties};
pub use refresh::{ExtractedRun, extract_run};
pub use refresh_configuration::{ExtractionResources, RefreshRequest, RunPaths, parse_timestamp};
