use crate::error::{Error, Result};

/// Parses an ISO 8601 timestamp or date in UTC to Unix seconds.
///
/// # Errors
/// Returns an error when the text is not a timestamp or precedes the Unix epoch.
pub fn parse_timestamp(value: &str) -> Result<i64> {
    let timestamp = if let Ok(parsed) = chrono::DateTime::parse_from_rfc3339(value) {
        parsed.timestamp()
    } else if let Ok(parsed) = chrono::NaiveDateTime::parse_from_str(value, "%Y-%m-%dT%H:%M:%S%.f")
    {
        parsed.and_utc().timestamp()
    } else {
        chrono::NaiveDate::parse_from_str(value, "%Y-%m-%d")
            .ok()
            .and_then(|date| date.and_hms_opt(0, 0, 0))
            .ok_or_else(|| Error::new("Invalid ISO 8601 timestamp"))?
            .and_utc()
            .timestamp()
    };
    if timestamp < 0 {
        return Err(Error::new("Timestamp precedes the Unix epoch"));
    }
    Ok(timestamp)
}

/// Formats Unix seconds as an RFC 3339 timestamp in UTC.
///
/// # Errors
/// Returns an error when the value is outside the supported range.
pub fn format_timestamp(value: i64) -> Result<String> {
    chrono::DateTime::from_timestamp(value, 0)
        .map(|date| date.to_rfc3339())
        .ok_or_else(|| Error::new("Timestamp is outside the supported range"))
}

/// Returns the UTC calendar date of a timestamp text, as `YYYY-MM-DD`.
///
/// # Errors
/// Returns an error when the text is not a timestamp.
pub fn date_text(value: &str) -> Result<String> {
    chrono::DateTime::from_timestamp(parse_timestamp(value)?, 0)
        .map(|date| date.format("%Y-%m-%d").to_string())
        .ok_or_else(|| Error::new("Timestamp is outside the supported range"))
}
