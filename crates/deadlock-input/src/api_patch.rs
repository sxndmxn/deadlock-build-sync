use chrono::{DateTime, NaiveDate, NaiveDateTime, Utc};
use deadlock_data::{Error, Result, canonical_json, fingerprint};
use serde_json::{Map, Value, json};

use crate::api_session::{ApiSession, object_rows};

#[derive(Clone, Debug)]
pub struct Patch {
    pub title: String,
    pub start_timestamp: i64,
    pub published_at: String,
    pub source: String,
    pub guid: String,
    pub link: String,
    pub content_sha256: String,
}

impl Patch {
    /// # Errors
    /// Returns an error when patch fields or the source fingerprint are invalid.
    pub fn from_document(value: &Value) -> Result<Self> {
        let patch = Self {
            title: deadlock_data::text(value, "title")?.into(),
            start_timestamp: i64::try_from(deadlock_data::integer(value, "start_timestamp")?)?,
            published_at: deadlock_data::text(value, "published_at")?.into(),
            source: deadlock_data::text(value, "source")?.into(),
            guid: deadlock_data::text(value, "guid")?.into(),
            link: deadlock_data::text(value, "link")?.into(),
            content_sha256: deadlock_data::text(value, "content_sha256")?.into(),
        };
        if value["identity"] != patch.identity()? {
            return Err(Error::new("Patch fingerprint differs from its contents"));
        }
        Ok(patch)
    }

    /// # Errors
    /// Returns an error when patch identity serialization fails.
    pub fn identity(&self) -> Result<String> {
        fingerprint(
            &json!({"source":self.source, "guid":self.guid, "published_at":self.published_at, "link":self.link, "content_sha256":self.content_sha256}),
        )
    }

    /// # Errors
    /// Returns an error when patch identity serialization fails.
    pub fn to_document(&self) -> Result<Map<String, Value>> {
        Ok(Map::from_iter([
            ("identity".into(), self.identity()?.into()),
            ("title".into(), self.title.clone().into()),
            ("start_timestamp".into(), self.start_timestamp.into()),
            ("published_at".into(), self.published_at.clone().into()),
            ("source".into(), self.source.clone().into()),
            ("guid".into(), self.guid.clone().into()),
            ("link".into(), self.link.clone().into()),
            ("content_sha256".into(), self.content_sha256.clone().into()),
        ]))
    }
}

pub fn current_patch(session: &mut ApiSession) -> Result<Patch> {
    let response = session.get("/v2/patches", Map::new())?;
    parse_patch_feed(&response, None)
}

/// # Errors
/// Returns an error when the patch feed is malformed or has no valid patch before the optional cutoff.
pub fn parse_patch_feed(response: &Value, as_of: Option<i64>) -> Result<Patch> {
    let rows = if response.is_object() {
        response
            .get("patches")
            .or_else(|| response.get("data"))
            .cloned()
            .ok_or_else(|| Error::new("Patch response has no patch list"))?
    } else {
        response.clone()
    };
    let mut latest: Option<(DateTime<Utc>, Value)> = None;
    for row in object_rows(rows, "Patch")? {
        if let Some(published) = row["pub_date"].as_str() {
            let timestamp = parse_datetime(published)?;
            if as_of.is_some_and(|cutoff| timestamp.timestamp() > cutoff) {
                continue;
            }
            if latest
                .as_ref()
                .is_none_or(|(current, _)| timestamp > *current)
            {
                latest = Some((timestamp, row));
            }
        }
    }
    let (timestamp, row) = latest.ok_or_else(|| Error::new("Patch response has no dated patch"))?;
    Ok(Patch {
        title: row["title"]
            .as_str()
            .filter(|value| !value.is_empty())
            .unwrap_or("Current patch")
            .into(),
        start_timestamp: timestamp.timestamp(),
        published_at: row["pub_date"]
            .as_str()
            .ok_or_else(|| Error::new("Patch date is missing"))?
            .into(),
        source: row["source"]
            .as_str()
            .filter(|value| !value.is_empty())
            .unwrap_or("unknown")
            .into(),
        guid: normalize_guid(&row["guid"])?,
        link: row["link"].as_str().unwrap_or_default().into(),
        content_sha256: fingerprint(&normalize_content(&row["content"]))?,
    })
}

fn parse_datetime(value: &str) -> Result<DateTime<Utc>> {
    if let Ok(value) = DateTime::parse_from_rfc3339(value) {
        return Ok(value.with_timezone(&Utc));
    }
    for format in ["%Y-%m-%dT%H:%M:%S%.f", "%Y-%m-%d %H:%M:%S%.f"] {
        if let Ok(value) = NaiveDateTime::parse_from_str(value, format) {
            return Ok(value.and_utc());
        }
    }
    NaiveDate::parse_from_str(value, "%Y-%m-%d")
        .ok()
        .and_then(|date| date.and_hms_opt(0, 0, 0))
        .map(|value| value.and_utc())
        .ok_or_else(|| Error::new(format!("Patch timestamp is invalid: {value}")))
}

fn normalize_guid(value: &Value) -> Result<String> {
    match value {
        Value::String(value) if !value.trim().is_empty() => Ok(value.trim().to_owned()),
        Value::Array(_) | Value::Object(_) => {
            String::from_utf8(canonical_json(value)?).map_err(|error| Error::new(error.to_string()))
        }
        _ => Ok("unknown".into()),
    }
}

fn normalize_content(value: &Value) -> Value {
    match value {
        Value::String(value) => normalize_cdn(value).into(),
        Value::Array(values) => values.iter().map(normalize_content).collect(),
        Value::Object(values) => Value::Object(
            values
                .iter()
                .map(|(key, value)| (key.clone(), normalize_content(value)))
                .collect(),
        ),
        value => value.clone(),
    }
}

fn normalize_cdn(value: &str) -> String {
    let lowercase = value.to_ascii_lowercase();
    let mut output = String::with_capacity(value.len());
    let mut copied = 0;
    for (index, _) in lowercase.match_indices("://") {
        let host_start = index + 3;
        let suffix = &lowercase[host_start..];
        for prefix in ["clan", "shared"] {
            for provider in ["akamai", "fastly"] {
                let host = format!("{prefix}.{provider}.steamstatic.com");
                if suffix.starts_with(&host) {
                    output.push_str(&value[copied..host_start]);
                    output.push_str(&value[host_start..host_start + prefix.len()]);
                    output.push_str(".cdn.steamstatic.com");
                    copied = host_start + host.len();
                }
            }
        }
    }
    output.push_str(&value[copied..]);
    output
}
