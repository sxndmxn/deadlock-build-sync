use chrono::{DateTime, NaiveDate, NaiveDateTime, Utc};
use deadlock_data::{Error, Patch, PatchPost, Result, canonical_json, fingerprint, text};
use serde_json::{Map, Value};

use crate::api_session::{ApiSession, object_rows};

/// Returns true when the title or text of a feed post contains the word "update".
///
/// Game updates use this word, for example "Minor Update" and "City Never Sleeps".
/// Hero release posts are stories without it.
fn is_game_update(row: &Value) -> bool {
    [&row["title"], &row["content"]]
        .iter()
        .filter_map(|value| value.as_str())
        .any(|text| {
            text.split(|character: char| !character.is_ascii_alphanumeric())
                .any(|word| word.eq_ignore_ascii_case("update"))
        })
}

pub fn current_patch(session: &ApiSession) -> Result<Patch> {
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
    let mut dated = Vec::new();
    for row in object_rows(rows, "Patch")? {
        let timestamp = parse_datetime(text(&row, "pub_date")?)?;
        if as_of.is_none_or(|cutoff| timestamp.timestamp() <= cutoff) {
            dated.push((timestamp, row));
        }
    }
    // Hero release posts are not patches. Use the latest game update, or the latest post
    // when the feed has no game update.
    let (timestamp, row) = dated
        .iter()
        .filter(|(_, row)| is_game_update(row))
        .max_by_key(|(timestamp, _)| *timestamp)
        .or_else(|| dated.iter().max_by_key(|(timestamp, _)| *timestamp))
        .cloned()
        .ok_or_else(|| Error::new("Patch response has no dated patch"))?;
    Patch::from_post(PatchPost {
        title: text(&row, "title")?.into(),
        start_timestamp: timestamp.timestamp(),
        published_at: text(&row, "pub_date")?.into(),
        source: text(&row, "source")?.into(),
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

/// Returns the GUID text, or the canonical JSON of a structured GUID.
fn normalize_guid(value: &Value) -> Result<String> {
    match value {
        Value::String(value) if !value.trim().is_empty() => Ok(value.trim().to_owned()),
        Value::Array(_) | Value::Object(_) => {
            String::from_utf8(canonical_json(value)?).map_err(|error| Error::new(error.to_string()))
        }
        _ => Err(Error::new("Patch post has no GUID")),
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

/// Replaces the changing CDN hosts of Steam images with one stable host.
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
