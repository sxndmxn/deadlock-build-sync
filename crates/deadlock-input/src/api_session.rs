use deadlock_data::{Error, Result};
use serde_json::{Map, Value};

use crate::api_options::ApiOptions;
use crate::http_client::JsonHttpClient;

#[derive(Debug)]
pub struct ApiSession {
    pub(super) options: ApiOptions,
    http: JsonHttpClient,
    client_version: Option<u64>,
}

impl ApiSession {
    pub(super) fn new(options: ApiOptions) -> Result<Self> {
        options.rank_range.validate()?;
        if options.client_version == Some(0) || options.as_of_timestamp < 0 {
            return Err(Error::new(
                "API client version must be positive and the cutoff must be nonnegative",
            ));
        }
        let http = JsonHttpClient::new(&options.base_url, options.timeout, 3)?;
        http.set_request_interval(options.request_interval)?;
        Ok(Self {
            options,
            http,
            client_version: None,
        })
    }

    pub(super) fn get(&self, path: &str, parameters: Map<String, Value>) -> Result<Value> {
        let normalized = parameters
            .into_iter()
            .filter_map(|(name, value)| match value {
                Value::Null => None,
                Value::Bool(value) => Some((name, value.to_string().into())),
                value => Some((name, value)),
            })
            .collect();
        self.http.get_json(path, &normalized)
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
            ("match_mode".into(), "ranked".into()),
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
