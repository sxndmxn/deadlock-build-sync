use std::path::Path;

use deadlock_data::{EpochBoundary, EpochSet, RankRange, Result, integer, text};
use deadlock_input::{ApiOptions, ApiResponseCache, DeadlockApi, Patch};
use serde_json::Value;

use crate::config::{cohort_ranks, parse_timestamp};
use crate::discovery_models::item_ids;
use crate::discovery_snapshot::FrozenRoster;

#[derive(Debug)]
pub struct AbilityPrefetch {
    options: ApiOptions,
    start: i64,
}

#[derive(Debug)]
struct AbilityRequest {
    hero_id: u64,
    ranks: RankRange,
    items: Vec<u64>,
}

impl AbilityPrefetch {
    pub fn new(output: &Path, manifest: &Value, patch: &Patch, base_url: &str) -> Result<Self> {
        let boundary = EpochBoundary {
            identity: patch.identity()?,
            start_timestamp: patch.start_timestamp,
        };
        Ok(Self {
            options: ApiOptions {
                base_url: base_url.into(),
                rank_range: cohort_ranks(&manifest["cohort"])?,
                match_mode: text(&manifest["cohort"], "match_mode")?.parse()?,
                client_version: Some(integer(&manifest["sources"], "client_version")?),
                as_of_timestamp: parse_timestamp(text(&manifest["cohort"], "as_of")?)?,
                epochs: Some(EpochSet {
                    mechanics: boundary.clone(),
                    matchmaking: boundary.clone(),
                    map_objectives: boundary.clone(),
                    telemetry: boundary,
                }),
                response_cache: Some(ApiResponseCache::refresh_for_evidence(output)),
                ..ApiOptions::default()
            },
            start: patch.start_timestamp,
        })
    }

    pub fn collect(&self, frozen: &FrozenRoster) -> Result<()> {
        let mut requests = Vec::new();
        for (hero_id, hero) in frozen {
            let ranks = cohort_ranks(&hero.cohort)?;
            requests.push(AbilityRequest {
                hero_id: *hero_id,
                ranks,
                items: Vec::new(),
            });
            for row in &hero.rows {
                requests.push(AbilityRequest {
                    hero_id: *hero_id,
                    ranks,
                    items: item_ids(&row.path["order"])?,
                });
            }
        }
        let mut api = DeadlockApi::new(self.options.clone())?;
        api.map_requests(&requests, 8, |api, request| {
            api.with_rank_range(request.ranks, |api| {
                api.ability_order_stats(request.hero_id, self.start, 1, &request.items)
                    .map(|_| ())
            })
        })?;
        Ok(())
    }
}
