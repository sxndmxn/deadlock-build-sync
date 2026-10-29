#![forbid(unsafe_code)]
#![deny(warnings)]

mod build_tag_catalog;
pub use build_tag_catalog::{BuildTag, BuildTagCatalog, FUNCTION_CLASSES};

mod api;
mod api_analytics;
mod api_assets;
mod api_options;
mod api_patch;
mod api_session;
mod http_client;
mod mechanics_text;

pub use api::DeadlockApi;
pub use api_options::{ApiOptions, DEFAULT_API_BASE_URL};
pub use api_patch::{Patch, parse_patch_feed};
pub use http_client::JsonHttpClient;
pub use mechanics_text::clean_mechanical_text;
