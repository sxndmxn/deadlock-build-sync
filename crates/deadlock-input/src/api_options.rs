use std::time::Duration;

use deadlock_data::RankRange;

pub const DEFAULT_API_BASE_URL: &str = "https://api.deadlock-api.com";

#[derive(Clone, Debug)]
pub struct ApiOptions {
    pub base_url: String,
    pub timeout: Duration,
    pub request_interval: Duration,
    pub rank_range: RankRange,
    pub client_version: Option<u64>,
    pub as_of_timestamp: i64,
}

impl Default for ApiOptions {
    fn default() -> Self {
        Self {
            base_url: DEFAULT_API_BASE_URL.into(),
            timeout: Duration::from_secs(60),
            request_interval: Duration::from_millis(310),
            rank_range: RankRange::default(),
            client_version: None,
            as_of_timestamp: chrono::Utc::now().timestamp(),
        }
    }
}
