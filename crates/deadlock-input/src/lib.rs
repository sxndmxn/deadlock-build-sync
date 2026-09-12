#![forbid(unsafe_code)]
#![deny(warnings)]

mod build_tag_catalog;
pub use build_tag_catalog::{
    AXIS_CLASSES, BuildTag, BuildTagCatalog, COMPLEXITY_CLASSES, FUNCTION_CLASSES,
};

mod api;
mod api_analytics;
mod api_assets;
mod api_cache;
mod api_options;
mod api_patch;
mod api_session;
mod category_bonus;
mod http;
mod item_graph;
mod item_node;
mod mechanics_assets;
mod mechanics_text;

pub use api::DeadlockApi;
pub use api_analytics::HeroDurationStat;
pub use api_cache::ApiResponseCache;
pub use api_options::{ApiOptions, DEFAULT_API_BASE_URL};
pub use api_patch::{Patch, parse_patch_feed};
pub use category_bonus::{CategoryBonus, CategoryBonusTable};
pub use http::{JsonHttpClient, JsonHttpResponse};
pub use item_graph::ItemGraph;
pub use item_node::ItemNode;
pub use mechanics_assets::{MECHANICS_FIELDS, build_hero_mechanics, extract_asset_mechanics};
pub use mechanics_text::{
    clean_mechanical_text, clean_text, is_populated, normalize_hero_description,
    normalize_mechanical_value,
};
