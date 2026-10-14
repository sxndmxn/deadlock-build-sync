//! Experiments that test the build method on extracted runs. See `docs/research-log.md`.

mod build_agreement;
mod counter_tests;
mod effect_models;

pub use build_agreement::{
    AgreementPair, LabelHalves, LandmarkAgreement, ScoringResult, compare_item_scoring,
    compare_scoring_by_landmark, compare_scoring_pair, compare_variant_agreement,
    measure_label_halves,
};
pub use counter_tests::{
    ConditionResult, CounterResult, WindowEvidence, estimate_counter_interactions,
    estimate_enemy_item_counters, measure_counter_windows,
};
pub use effect_models::{
    EffectModel, Interaction, ItemEffectRow, ModelResult, compare_effect_models,
    estimate_split_item_effects,
};
