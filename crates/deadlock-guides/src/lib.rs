#![forbid(unsafe_code)]
#![deny(warnings)]

mod ability_focus;
mod ability_order;
mod build_tag_catalog;
mod build_tags;
mod build_text;
mod build_title;
mod hero_build;
mod hero_presentation;
mod mechanics_text;
mod presentation;

pub use ability_focus::assign_build_focus;
pub use ability_order::{AbilityPath, select_ability_path};
pub use build_tag_catalog::BuildTagCatalog;
pub use build_tags::assign_build_tags;
pub use build_text::{
    BEST_TITLE_PREFIX, MAIN_CORE_PANEL, ability_order, display_title, evidence, format_soul_window,
    format_souls, main_comparison, phase_label, play_around, rank_label, tier_panel_name,
    variant_note, win_rate,
};
pub use hero_build::{
    AbilityFocus, BuildCohort, BuildContrast, BuildEvaluation, BuildItem, BuildRules,
    CONTRAST_BETTER_Z, CONTRAST_REMOVAL_Z, Confidence, CounterEvidence, CounterPanel, CounterPhase,
    CounterTarget, HERO_BUILD_METHOD, HERO_BUILD_SCHEMA_VERSION, HeroBuild, HeroBuildCatalog,
    HeroEstimate, ImbueTarget, ItemStatistics, MAXIMUM_COUNTER_ITEMS, log_odds_to_win_points,
};
pub use hero_presentation::build_hero_presentation;
pub use presentation::{
    BuildPresentation, LEGACY_MANAGED_MARKER, MANAGED_MARKER, ManagedTrailer,
    PresentationAbilities, PresentationCategory, PresentationContent, PresentationItem,
    is_build_path,
};
