use std::time::Duration;

use deadlock_data::RankRange;

pub const DEFAULT_API_BASE_URL: &str = "https://api.deadlock-api.com";
/// The API allows about three requests a second. Every client of this crate waits this long
/// between requests.
pub const REQUEST_INTERVAL: Duration = Duration::from_millis(310);

#[derive(Clone, Debug)]
pub struct ApiOptions {
    pub base_url: String,
    pub rank_range: RankRange,
    pub client_version: Option<u64>,
    pub as_of_timestamp: i64,
}

impl Default for ApiOptions {
    fn default() -> Self {
        Self {
            base_url: DEFAULT_API_BASE_URL.into(),
            rank_range: RankRange::default(),
            client_version: None,
            as_of_timestamp: chrono::Utc::now().timestamp(),
        }
    }
}
