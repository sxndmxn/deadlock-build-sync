#![forbid(unsafe_code)]
#![deny(warnings)]

mod ability_order;
mod ability_path;
mod build_tags;
mod build_title;
mod hero_build;
mod hero_presentation;
mod presentation;

pub use ability_order::select_ability_path;
pub use ability_path::AbilityPath;
pub use build_tags::{BuildTagSelection, TagItem, select_build_tags};
pub use hero_build::{
    BuildCohort, BuildEvaluation, BuildItem, Confidence, HERO_BUILD_METHOD,
    HERO_BUILD_SCHEMA_VERSION, HeroBuild, HeroBuildCatalog,
};
pub use hero_presentation::build_hero_presentation;
pub use presentation::{
    BuildPresentation, LEGACY_MANAGED_MARKER, MANAGED_MARKER, PresentationAbilities,
    PresentationCategory, PresentationContent, PresentationItem,
};
