use deadlock_data::Result;
use serde_json::Value;

use crate::api_analytics;
use crate::api_assets;
use crate::api_options::ApiOptions;
use crate::api_patch::{self, Patch};
use crate::api_session::ApiSession;

#[derive(Debug)]
pub struct DeadlockApi {
    session: ApiSession,
}

impl DeadlockApi {
    /// # Errors
    /// Returns an error for invalid connection settings or source boundaries.
    pub fn new(options: ApiOptions) -> Result<Self> {
        Ok(Self {
            session: ApiSession::new(options)?,
        })
    }

    /// # Errors
    /// Returns an error when the requested client version is unavailable.
    pub fn resolve_client_version(&mut self) -> Result<u64> {
        self.session.resolve_client_version()
    }

    /// # Errors
    /// Returns an error for unavailable or malformed build tag assets.
    pub fn build_tags(&mut self) -> Result<Vec<Value>> {
        api_assets::build_tags(&mut self.session)
    }

    /// # Errors
    /// Returns an error when the patch feed has no valid current patch.
    pub fn current_patch(&mut self) -> Result<Patch> {
        api_patch::current_patch(&self.session)
    }

    /// # Errors
    /// Returns an error for invalid query boundaries or unavailable statistics.
    pub fn ability_order_stats(
        &mut self,
        hero_id: u64,
        minimum_timestamp: i64,
        minimum_matches: u32,
        item_ids: &[u64],
    ) -> Result<Vec<Value>> {
        api_analytics::ability_order_stats(
            &self.session,
            hero_id,
            minimum_timestamp,
            minimum_matches,
            item_ids,
        )
    }
}
