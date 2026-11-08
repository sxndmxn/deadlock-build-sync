//! The API inputs of a production run: build tag assets and ability order statistics.
//!
//! The first build of a run requests them and records them in the run directory.
//! A resumed run reads the record, so it produces the same catalog as the first build.

use std::collections::BTreeMap;

use deadlock_data::{Error, Result, atomic_write_json, read_json};
use deadlock_input::DeadlockApi;
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::refresh_configuration::RunPaths;

/// The record file in the `raw` directory of a run.
pub const API_INPUTS_FILE: &str = "api-inputs.json";
const ABILITY_MINIMUM_MATCHES: u32 = 10;
const ABILITY_REQUEST_THREADS: usize = 4;

/// One ability order request: the hero and the items that its players must own.
pub type AbilityRequest = (u64, Vec<u64>);

#[derive(Debug, Default, Deserialize, Serialize)]
struct RecordedInputs {
    build_tags: Option<Vec<Value>>,
    ability_orders: Vec<AbilityOrderRecord>,
}

#[derive(Debug, Deserialize, Serialize)]
struct AbilityOrderRecord {
    hero_id: u64,
    item_ids: Vec<u64>,
    rows: Vec<Value>,
}

/// The build tag assets and the ability order rows of each request.
#[derive(Debug, Default)]
pub struct ApiInputs {
    build_tags: Option<Vec<Value>>,
    ability_orders: BTreeMap<AbilityRequest, Vec<Value>>,
    changed: bool,
}

impl ApiInputs {
    /// Reads the record of a run. A run without a record has no inputs yet.
    ///
    /// # Errors
    /// Returns an error when the record exists and is malformed.
    pub fn load(paths: &RunPaths) -> Result<Self> {
        let path = paths.raw.join(API_INPUTS_FILE);
        if !path.is_file() {
            return Ok(Self::default());
        }
        let recorded: RecordedInputs = serde_json::from_value(read_json(&path)?)
            .map_err(|error| Error::new(format!("Malformed {API_INPUTS_FILE}: {error}")))?;
        Ok(Self {
            build_tags: recorded.build_tags,
            ability_orders: recorded
                .ability_orders
                .into_iter()
                .map(|record| ((record.hero_id, record.item_ids), record.rows))
                .collect(),
            changed: false,
        })
    }

    /// Writes the record when new inputs were added since the load.
    ///
    /// # Errors
    /// Returns an error when the write fails.
    pub fn save(&self, paths: &RunPaths) -> Result<()> {
        if !self.changed {
            return Ok(());
        }
        let recorded = RecordedInputs {
            build_tags: self.build_tags.clone(),
            ability_orders: self
                .ability_orders
                .iter()
                .map(|((hero_id, item_ids), rows)| AbilityOrderRecord {
                    hero_id: *hero_id,
                    item_ids: item_ids.clone(),
                    rows: rows.clone(),
                })
                .collect(),
        };
        atomic_write_json(
            &paths.raw.join(API_INPUTS_FILE),
            &serde_json::to_value(recorded)?,
        )
    }

    /// # Errors
    /// Returns an error when the build tags were neither recorded nor requested.
    pub fn build_tags(&self) -> Result<&[Value]> {
        self.build_tags
            .as_deref()
            .ok_or_else(|| Error::new("Build tag assets were not requested"))
    }

    /// Returns the recorded rows of a request, or no rows.
    #[must_use]
    pub fn ability_rows(&self, request: &AbilityRequest) -> &[Value] {
        self.ability_orders.get(request).map_or(&[], Vec::as_slice)
    }

    /// Returns the requests without recorded rows, in request order.
    #[must_use]
    pub fn missing_requests(&self, requests: &[AbilityRequest]) -> Vec<AbilityRequest> {
        requests
            .iter()
            .filter(|request| !self.ability_orders.contains_key(*request))
            .cloned()
            .collect()
    }

    #[must_use]
    pub const fn has_build_tags(&self) -> bool {
        self.build_tags.is_some()
    }

    /// Adds requested inputs to the record.
    pub fn record(&mut self, requested: RequestedInputs) {
        if let Some(tags) = requested.build_tags {
            self.build_tags = Some(tags);
            self.changed = true;
        }
        if !requested.ability_orders.is_empty() {
            self.ability_orders.extend(requested.ability_orders);
            self.changed = true;
        }
    }
}

/// Inputs that one request round returned.
#[derive(Debug, Default)]
pub struct RequestedInputs {
    pub build_tags: Option<Vec<Value>>,
    pub ability_orders: BTreeMap<AbilityRequest, Vec<Value>>,
}

/// Requests the build tags, when asked, and the ability orders of the requests.
///
/// # Errors
/// Returns an error when a request fails after its retries.
pub fn request_inputs(
    api: &mut DeadlockApi,
    build_tags: bool,
    requests: &[AbilityRequest],
    since: i64,
) -> Result<RequestedInputs> {
    let build_tags = if build_tags {
        Some(api.build_tags()?)
    } else {
        None
    };
    if !requests.is_empty() {
        eprintln!("Requesting ability orders for {} builds", requests.len());
    }
    Ok(RequestedInputs {
        build_tags,
        ability_orders: request_ability_orders(api, requests, since)?,
    })
}

/// Requests the ability orders from several threads.
///
/// An uncached request takes about 1 s. The client still starts at most one request
/// in each request interval, so the threads do not increase the request rate.
fn request_ability_orders(
    api: &DeadlockApi,
    requests: &[AbilityRequest],
    since: i64,
) -> Result<BTreeMap<AbilityRequest, Vec<Value>>> {
    std::thread::scope(|scope| {
        let threads = (0..ABILITY_REQUEST_THREADS)
            .map(|first| {
                let assigned = requests
                    .iter()
                    .skip(first)
                    .step_by(ABILITY_REQUEST_THREADS)
                    .cloned()
                    .collect::<Vec<_>>();
                scope.spawn(move || {
                    assigned
                        .into_iter()
                        .map(|(hero_id, items)| {
                            let rows = api.ability_order_stats(
                                hero_id,
                                since,
                                ABILITY_MINIMUM_MATCHES,
                                &items,
                            )?;
                            Ok(((hero_id, items), rows))
                        })
                        .collect::<Result<Vec<_>>>()
                })
            })
            .collect::<Vec<_>>();
        let mut rows = BTreeMap::new();
        for thread in threads {
            rows.extend(
                thread
                    .join()
                    .map_err(|_| Error::new("Ability order requests stopped unexpectedly"))??,
            );
        }
        Ok(rows)
    })
}
