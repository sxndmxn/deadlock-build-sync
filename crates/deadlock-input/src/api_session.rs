use deadlock_data::{
    Error, EvidenceRecorder, EvidenceSemantics, EvidenceUnit, Result, fingerprint,
};
use serde_json::{Map, Value, json};

use crate::api_cache::CachedResponse;
use crate::api_options::ApiOptions;
use crate::http::JsonHttpClient;

#[derive(Debug)]
pub struct ApiSession {
    pub(super) options: ApiOptions,
    pub(super) recorder: EvidenceRecorder,
    http: JsonHttpClient,
    client_version: Option<u64>,
}

impl ApiSession {
    pub(super) fn fork(&self) -> Self {
        Self {
            options: self.options.clone(),
            recorder: self.recorder.fork(),
            http: self.http.clone(),
            client_version: self.client_version,
        }
    }

    pub(super) fn new(options: ApiOptions) -> Result<Self> {
        options.rank_range.validate()?;
        if options.client_version == Some(0) || options.as_of_timestamp < 0 {
            return Err(Error::new(
                "API client version must be positive and the cutoff must be nonnegative",
            ));
        }
        if let Some(epochs) = &options.epochs {
            epochs.validate()?;
        }
        let http = JsonHttpClient::new(&options.base_url, options.timeout, 3)?;
        http.set_request_interval(options.request_interval)?;
        let mut session = Self {
            options,
            http,
            recorder: EvidenceRecorder::default(),
            client_version: None,
        };
        session.declare_routes()?;
        Ok(session)
    }

    fn declare_routes(&mut self) -> Result<()> {
        for (path, grain, unit) in [
            (
                "/v1/assets/client-versions",
                "available-client-version",
                EvidenceUnit::Asset,
            ),
            ("/v1/assets/heroes", "hero-asset", EvidenceUnit::Asset),
            (
                "/v1/assets/items",
                "item-or-ability-asset",
                EvidenceUnit::Asset,
            ),
            (
                "/v1/assets/build-tags",
                "build-tag-asset",
                EvidenceUnit::Asset,
            ),
            ("/v1/assets/ranks", "rank-tier-asset", EvidenceUnit::Asset),
            ("/v2/patches", "patch-feed-entry", EvidenceUnit::Asset),
            (
                "/v1/players/steam",
                "steam-account-profile",
                EvidenceUnit::Asset,
            ),
            (
                "/v1/analytics/ability-order-stats",
                "observed-ability-prefix",
                EvidenceUnit::AbilityPath,
            ),
            (
                "/v1/analytics/hero-stats",
                "ending-duration-hero-appearance",
                EvidenceUnit::HeroAppearance,
            ),
            (
                "/v1/analytics/hero-counter-stats",
                "hero-enemy-pair",
                EvidenceUnit::HeroEnemyPair,
            ),
        ] {
            self.recorder.declare(
                path,
                EvidenceSemantics {
                    unit,
                    backend_grain: grain.into(),
                    fallback_behavior: "reject; never change population or grain".into(),
                    warnings: Vec::new(),
                },
            )?;
        }
        Ok(())
    }

    pub(super) fn get(&mut self, path: &str, parameters: Map<String, Value>) -> Result<Value> {
        let normalized = parameters
            .into_iter()
            .filter_map(|(name, value)| match value {
                Value::Null => None,
                Value::Bool(value) => Some((name, value.to_string().into())),
                value => Some((name, value)),
            })
            .collect::<Map<_, _>>();
        let response = self.get_response(path, &normalized)?;
        self.recorder
            .record(path, normalized, &response.content, response.fetched_at)?;
        Ok(response.data)
    }

    fn get_response(&self, path: &str, parameters: &Map<String, Value>) -> Result<CachedResponse> {
        let cache = self.options.response_cache.as_ref().filter(|_| {
            path == "/v1/analytics/ability-order-stats" && self.options.client_version.is_some()
        });
        let identity = if cache.is_some() {
            fingerprint(&json!({"base_url":self.options.base_url,"path":path,
                "parameters":parameters,"client_version":self.options.client_version,
                "epochs":self.options.epochs}))?
        } else {
            String::new()
        };
        if let Some(cache) = cache
            && let Some(response) = cache.read(&identity)?
        {
            return Ok(response);
        }
        let response = self
            .http
            .get_json(path, &parameters.clone().into_iter().collect())?;
        let response = CachedResponse {
            content: response.content,
            data: response.data,
            fetched_at: chrono::Utc::now(),
        };
        if let Some(cache) = cache {
            cache.write(&identity, &response)?;
        }
        Ok(response)
    }

    pub(super) fn resolve_client_version(&mut self) -> Result<u64> {
        if let Some(version) = self.client_version {
            return Ok(version);
        }
        let versions = self.get("/v1/assets/client-versions", Map::new())?;
        let versions = versions
            .as_array()
            .ok_or_else(|| Error::new("Client version response must be a list"))?
            .iter()
            .filter_map(Value::as_u64)
            .filter(|version| *version > 0)
            .collect::<Vec<_>>();
        let selected = if let Some(requested) = self.options.client_version {
            if !versions.contains(&requested) {
                return Err(Error::new(format!(
                    "Requested client version {requested} is unavailable"
                )));
            }
            requested
        } else {
            versions
                .into_iter()
                .max()
                .ok_or_else(|| Error::new("API returned no client versions"))?
        };
        self.client_version = Some(selected);
        Ok(selected)
    }

    pub(super) fn asset_parameters(&mut self) -> Result<Map<String, Value>> {
        Ok(Map::from_iter([(
            "client_version".into(),
            self.resolve_client_version()?.into(),
        )]))
    }

    pub(super) fn analytic_parameters(&self, minimum_timestamp: i64) -> Result<Map<String, Value>> {
        if minimum_timestamp < 0 || minimum_timestamp > self.options.as_of_timestamp {
            return Err(Error::new(
                "Analysis start must be nonnegative and must not exceed the frozen cutoff",
            ));
        }
        let mut parameters = self.options.rank_range.api_parameters();
        parameters.extend([
            ("game_mode".into(), "normal".into()),
            ("match_mode".into(), self.options.match_mode.as_str().into()),
            ("min_unix_timestamp".into(), minimum_timestamp.into()),
            (
                "max_unix_timestamp".into(),
                self.options.as_of_timestamp.into(),
            ),
        ]);
        Ok(parameters)
    }
}

pub fn object_rows(value: Value, label: &str) -> Result<Vec<Value>> {
    match value {
        Value::Array(rows) if rows.iter().all(Value::is_object) => Ok(rows),
        _ => Err(Error::new(format!(
            "{label} response must be a list of objects"
        ))),
    }
}
