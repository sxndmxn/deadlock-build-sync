#![forbid(unsafe_code)]
#![deny(warnings)]

mod api;
mod api_analytics;
mod api_assets;
mod api_options;
mod api_patch;
mod api_session;
mod http_client;

pub use api::DeadlockApi;
pub use api_options::{ApiOptions, DEFAULT_API_BASE_URL, REQUEST_INTERVAL};
pub use api_patch::parse_patch_feed;
pub use http_client::JsonHttpClient;
