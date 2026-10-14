//! Experiments that test the build method on extracted runs. See `docs/research-log.md`.

mod build_agreement;
mod counter_tests;
mod effect_models;

pub use build_agreement::{
    AgreementPair, BuildStability, FractionResult, LabelHalves, LandmarkAgreement, ScoringResult,
    compare_item_scoring, compare_scoring_by_landmark, compare_scoring_pair,
    compare_situational_signal, compare_training_fractions, compare_variant_agreement,
    measure_build_stability, measure_label_halves, measure_label_placebo, measure_pair_placebo,
};
pub use counter_tests::{
    ConditionResult, CounterResult, PlaceboResult, WindowEvidence, estimate_counter_interactions,
    estimate_enemy_item_counters, measure_counter_placebo, measure_counter_windows,
};
pub use effect_models::{
    EffectModel, Interaction, ItemEffectRow, ModelResult, compare_effect_models,
    estimate_split_item_effects,
};

/// Mixes the bits of a number for a fixed pseudo-random order in placebo tests.
const fn mix(value: u64) -> u64 {
    let value = (value ^ (value >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
    let value = (value ^ (value >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
    value ^ (value >> 31)
}
