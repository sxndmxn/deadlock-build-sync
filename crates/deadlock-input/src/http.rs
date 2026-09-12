use std::collections::BTreeMap;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use deadlock_data::{Error, Result, trace_operation};
use serde_json::Value;
use ureq::ResponseExt as _;
use ureq::http::Uri;

const MAXIMUM_RESPONSE_BYTES: u64 = 512 * 1024 * 1024;

#[derive(Debug)]
pub struct JsonHttpResponse {
    pub data: Value,
    pub content: Vec<u8>,
    pub url: String,
}

#[derive(Debug)]
struct RequestSchedule {
    minimum_interval: Duration,
    next_request: Instant,
}

#[derive(Clone, Debug)]
pub struct JsonHttpClient {
    base_url: String,
    agent: ureq::Agent,
    maximum_attempts: u32,
    schedule: Arc<Mutex<RequestSchedule>>,
}

#[derive(Debug)]
enum Attempt {
    Complete(JsonHttpResponse),
    Retry {
        error: Error,
        delay: Duration,
        rate_limited: bool,
    },
    Failed(Error),
}

impl JsonHttpClient {
    /// # Errors
    /// Returns an error if the URL, timeout, or attempt count is invalid.
    pub fn new(base_url: &str, timeout: Duration, maximum_attempts: u32) -> Result<Self> {
        let uri: Uri = base_url
            .parse()
            .map_err(|error| Error::new(format!("Invalid base URL: {error}")))?;
        if !matches!(uri.scheme_str(), Some("http" | "https"))
            || uri.host().is_none_or(str::is_empty)
            || uri.query().is_some()
            || uri
                .authority()
                .is_some_and(|value| value.as_str().contains('@'))
        {
            return Err(Error::new(
                "Base URL must be an absolute HTTP(S) URL without credentials or a query",
            ));
        }
        if timeout.is_zero() || maximum_attempts == 0 {
            return Err(Error::new("Timeout and maximum attempts must be positive"));
        }
        let configuration = ureq::Agent::config_builder()
            .timeout_global(Some(timeout))
            .http_status_as_error(false)
            .build();
        Ok(Self {
            base_url: base_url.trim_end_matches('/').to_owned(),
            agent: configuration.into(),
            maximum_attempts,
            schedule: Arc::new(Mutex::new(RequestSchedule {
                minimum_interval: Duration::ZERO,
                next_request: Instant::now(),
            })),
        })
    }

    /// # Errors
    /// Returns an error if a previous request interrupted the shared schedule.
    pub fn set_request_interval(&self, minimum_interval: Duration) -> Result<()> {
        self.schedule
            .lock()
            .map_err(|_| Error::new("Request schedule lock failed"))?
            .minimum_interval = minimum_interval;
        Ok(())
    }

    /// # Errors
    /// Returns an error if the parameters, response, or request schedule is invalid.
    pub fn get_json(
        &self,
        path: &str,
        parameters: &BTreeMap<String, Value>,
    ) -> Result<JsonHttpResponse> {
        trace_operation("input.http.get_json", None, || {
            self.request_json(path, parameters)
        })
    }

    fn request_json(
        &self,
        path: &str,
        parameters: &BTreeMap<String, Value>,
    ) -> Result<JsonHttpResponse> {
        let url = format!("{}/{}", self.base_url, path.trim_start_matches('/'));
        let parameters = query_parameters(parameters)?;
        for attempt in 0..self.maximum_attempts {
            self.wait_for_request_slot()?;
            match self.attempt(&url, &parameters, attempt) {
                Attempt::Complete(response) => return Ok(response),
                Attempt::Failed(error) => return Err(error.context("JSON GET failed")),
                Attempt::Retry {
                    error,
                    delay,
                    rate_limited,
                } => {
                    if attempt + 1 == self.maximum_attempts {
                        return Err(error.context("JSON GET failed after retries"));
                    }
                    if rate_limited {
                        self.postpone_requests(delay)?;
                    }
                    std::thread::sleep(delay);
                }
            }
        }
        Err(Error::new("JSON GET has no permitted attempts"))
    }

    fn wait_for_request_slot(&self) -> Result<()> {
        let mut schedule = self
            .schedule
            .lock()
            .map_err(|_| Error::new("Request schedule lock failed"))?;
        let delay = schedule
            .next_request
            .saturating_duration_since(Instant::now());
        if !delay.is_zero() {
            std::thread::sleep(delay);
        }
        schedule.next_request = Instant::now()
            .checked_add(schedule.minimum_interval)
            .ok_or_else(|| Error::new("Request interval exceeds the clock range"))?;
        drop(schedule);
        Ok(())
    }

    fn postpone_requests(&self, delay: Duration) -> Result<()> {
        let mut schedule = self
            .schedule
            .lock()
            .map_err(|_| Error::new("Request schedule lock failed"))?;
        let earliest = Instant::now()
            .checked_add(delay)
            .ok_or_else(|| Error::new("Retry delay exceeds the clock range"))?;
        schedule.next_request = schedule.next_request.max(earliest);
        drop(schedule);
        Ok(())
    }

    fn attempt(&self, url: &str, parameters: &[(String, String)], attempt: u32) -> Attempt {
        let response = self
            .agent
            .get(url)
            .query_pairs(
                parameters
                    .iter()
                    .map(|(key, value)| (key.as_str(), value.as_str())),
            )
            .header("Accept", "application/json")
            .header("User-Agent", "deadlock-build-sync/0.1")
            .call();
        let mut response = match response {
            Ok(response) => response,
            Err(error) => return retry(Error::new(error.to_string()), attempt),
        };
        let status = response.status();
        if !status.is_success() {
            let error = Error::new(format!("HTTP status {}", status.as_u16()));
            if status.as_u16() == 429 {
                let delay = response
                    .headers()
                    .get("retry-after")
                    .and_then(|value| value.to_str().ok())
                    .and_then(|value| value.parse::<f64>().ok())
                    .filter(|value| value.is_finite())
                    .and_then(|value| Duration::try_from_secs_f64(value.clamp(0.0, 30.0)).ok())
                    .unwrap_or_else(|| retry_delay(attempt));
                return Attempt::Retry {
                    error,
                    delay,
                    rate_limited: true,
                };
            }
            return if status.is_server_error() {
                retry(error, attempt)
            } else {
                Attempt::Failed(error)
            };
        }
        let final_url = response.get_uri().to_string();
        let content = match response
            .body_mut()
            .with_config()
            .limit(MAXIMUM_RESPONSE_BYTES)
            .read_to_vec()
        {
            Ok(content) => content,
            Err(error) => return retry(Error::new(error.to_string()), attempt),
        };
        match serde_json::from_slice(&content) {
            Ok(data) => Attempt::Complete(JsonHttpResponse {
                data,
                content,
                url: final_url,
            }),
            Err(error) => retry(Error::from(error), attempt),
        }
    }
}

fn query_parameters(parameters: &BTreeMap<String, Value>) -> Result<Vec<(String, String)>> {
    let mut pairs = Vec::new();
    for (key, value) in parameters {
        if let Value::Array(values) = value {
            for value in values {
                pairs.push((key.clone(), query_scalar(key, value)?));
            }
        } else {
            pairs.push((key.clone(), query_scalar(key, value)?));
        }
    }
    Ok(pairs)
}

fn query_scalar(key: &str, value: &Value) -> Result<String> {
    match value {
        Value::Null => Ok(String::new()),
        Value::String(value) => Ok(value.clone()),
        Value::Bool(value) => Ok(value.to_string()),
        Value::Number(value) => Ok(value.to_string()),
        Value::Array(_) | Value::Object(_) => {
            Err(Error::new(format!("Invalid query value: {key}")))
        }
    }
}

fn retry(error: Error, attempt: u32) -> Attempt {
    Attempt::Retry {
        error,
        delay: retry_delay(attempt),
        rate_limited: false,
    }
}

fn retry_delay(attempt: u32) -> Duration {
    Duration::from_secs(1_u64.checked_shl(attempt).unwrap_or(u64::MAX).min(30))
}
