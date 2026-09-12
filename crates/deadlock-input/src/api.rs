use std::collections::BTreeMap;

use deadlock_data::{
    EpochBoundary, EpochSet, EvidenceRecorder, RankCatalog, Result, SnapshotContent,
    SnapshotManifest, default_outcome_policy,
};
use serde_json::Value;

use crate::api_analytics::{self, HeroDurationStat};
use crate::api_assets;
use crate::api_options::ApiOptions;
use crate::api_patch::{self, Patch};
use crate::api_session::ApiSession;

#[derive(Debug)]
pub struct DeadlockApi {
    session: ApiSession,
}

impl DeadlockApi {
    /// Runs requests on standard threads with one shared request schedule.
    /// Records responses and returns results in source order.
    /// # Errors
    /// Returns an error for zero workers, a failed operation, or an unexpected worker stop.
    pub fn map_requests<T: Sync, R: Send>(
        &mut self,
        jobs: &[T],
        workers: u16,
        operation: impl Fn(&mut Self, &T) -> Result<R> + Sync,
    ) -> Result<Vec<R>> {
        let results = deadlock_data::map_jobs(jobs, workers, |job| {
            let mut client = Self {
                session: self.session.fork(),
            };
            let result = operation(&mut client, job)?;
            Ok((result, client.session.recorder))
        })?;
        let mut values = Vec::with_capacity(results.len());
        for (value, recorder) in results {
            self.session.recorder.append(recorder);
            values.push(value);
        }
        Ok(values)
    }

    /// # Errors
    /// Returns an error for invalid connection settings or source boundaries.
    pub fn new(options: ApiOptions) -> Result<Self> {
        Ok(Self {
            session: ApiSession::new(options)?,
        })
    }

    #[must_use]
    pub const fn options(&self) -> &ApiOptions {
        &self.session.options
    }

    /// # Errors
    /// Returns an error when ranks are invalid or the operation fails. The method restores the original rank range.
    pub fn with_rank_range<T>(
        &mut self,
        ranks: deadlock_data::RankRange,
        operation: impl FnOnce(&mut Self) -> Result<T>,
    ) -> Result<T> {
        let previous = self.session.options.rank_range;
        self.session.options.rank_range = ranks.validate()?;
        let result = operation(self);
        self.session.options.rank_range = previous;
        result
    }

    pub const fn recorder_mut(&mut self) -> &mut EvidenceRecorder {
        &mut self.session.recorder
    }

    #[must_use]
    pub const fn recorder(&self) -> &EvidenceRecorder {
        &self.session.recorder
    }

    /// # Errors
    /// Returns an error when the requested client version is unavailable.
    pub fn resolve_client_version(&mut self) -> Result<u64> {
        self.session.resolve_client_version()
    }

    /// # Errors
    /// Returns an error for unavailable or malformed hero assets.
    pub fn active_heroes(&mut self) -> Result<Vec<Value>> {
        api_assets::active_heroes(&mut self.session)
    }

    /// # Errors
    /// Returns an error for unavailable or malformed item assets.
    pub fn items(&mut self) -> Result<Vec<Value>> {
        api_assets::items(&mut self.session)
    }

    /// # Errors
    /// Returns an error for unavailable or malformed build tag assets.
    pub fn build_tags(&mut self) -> Result<Vec<Value>> {
        api_assets::build_tags(&mut self.session)
    }

    /// # Errors
    /// Returns an error for unavailable or incomplete rank assets.
    pub fn rank_catalog(&mut self) -> Result<RankCatalog> {
        api_assets::rank_catalog(&mut self.session)
    }

    /// # Errors
    /// Returns an error when the patch feed has no valid current patch.
    pub fn current_patch(&mut self) -> Result<Patch> {
        api_patch::current_patch(&mut self.session)
    }

    /// # Errors
    /// Returns an error when the account has no available Steam persona name.
    pub fn steam_persona(&mut self, account_id: u32) -> Result<String> {
        api_assets::steam_persona(&mut self.session, account_id)
    }

    /// # Errors
    /// Returns an error for invalid query boundaries or unavailable statistics.
    pub fn item_stats(
        &mut self,
        hero_id: u64,
        minimum_timestamp: i64,
        minimum_matches: u32,
        bucket: Option<&str>,
    ) -> Result<Vec<Value>> {
        api_analytics::item_stats(
            &mut self.session,
            hero_id,
            minimum_timestamp,
            minimum_matches,
            bucket,
        )
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
            &mut self.session,
            hero_id,
            minimum_timestamp,
            minimum_matches,
            item_ids,
        )
    }

    /// # Errors
    /// Returns an error for invalid query boundaries or unavailable statistics.
    pub fn hero_counter_stats(
        &mut self,
        minimum_timestamp: i64,
        same_lane: bool,
    ) -> Result<Vec<Value>> {
        api_analytics::hero_counter_stats(&mut self.session, minimum_timestamp, same_lane)
    }

    /// # Errors
    /// Returns an error for invalid query boundaries or unavailable statistics.
    pub fn hero_stats_by_duration(
        &mut self,
        minimum_timestamp: i64,
    ) -> Result<BTreeMap<u64, Vec<HeroDurationStat>>> {
        api_analytics::hero_stats_by_duration(&mut self.session, minimum_timestamp)
    }

    /// # Errors
    /// Returns an error when a patch cannot supply a valid epoch boundary.
    pub fn epochs_for_patch(&self, patch: &Patch) -> Result<EpochSet> {
        if let Some(epochs) = &self.session.options.epochs {
            return Ok(epochs.clone());
        }
        let boundary = EpochBoundary {
            identity: patch.identity()?,
            start_timestamp: patch.start_timestamp,
        };
        boundary.validate()?;
        Ok(EpochSet {
            mechanics: boundary.clone(),
            matchmaking: boundary.clone(),
            map_objectives: boundary.clone(),
            telemetry: boundary,
        })
    }

    /// # Errors
    /// Returns an error when source identities or the frozen evidence window are incomplete.
    pub fn snapshot_manifest(
        &mut self,
        patch: &Patch,
        ranks: &RankCatalog,
        build_tags_sha256: &str,
    ) -> Result<SnapshotManifest> {
        let client_version = self.resolve_client_version()?;
        let options = &self.session.options;
        let warnings = if options.epochs.is_none() {
            vec!["The public patch feed has no independent epoch feeds. Each epoch uses the selected patch boundary.".into(), "Public aggregate routes cannot enforce every player eligibility exclusion. The results describe observed outcomes.".into()]
        } else {
            Vec::new()
        };
        SnapshotManifest::new(SnapshotContent {
            schema_version: 1,
            client_version,
            as_of_timestamp: options.as_of_timestamp,
            created_at: chrono::Utc::now().to_rfc3339(),
            match_mode: options.match_mode,
            game_mode: "normal".into(),
            rank_range: ranks.range_document(options.rank_range)?,
            rank_labels_sha256: ranks.fingerprint().into(),
            build_tags_sha256: build_tags_sha256.into(),
            patch: patch.to_document()?,
            epochs: self.epochs_for_patch(patch)?,
            outcome_policy: default_outcome_policy(false),
            records: self.session.recorder.records().to_vec(),
            warnings,
        })
    }
}
