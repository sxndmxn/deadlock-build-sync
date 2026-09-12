use chrono::DateTime;
use deadlock_data::{Error, Result};
use regex_lite::Regex;

pub const MAX_BUILD_NAME_CHARACTERS: usize = 50;

pub fn format_date(timestamp: u64, compact: bool) -> Result<String> {
    if timestamp == 0 {
        return Ok(if compact { "????" } else { "UNRESOLVED" }.into());
    }
    let time = DateTime::from_timestamp(i64::try_from(timestamp)?, 0)
        .ok_or_else(|| Error::new("Build timestamp is outside the supported date range"))?;
    Ok(time
        .format(if compact { "%m%d" } else { "%Y-%m-%d" })
        .to_string())
}

/// # Errors
/// Returns an error when the persona is empty, the statistics window is too long, or the patch pattern cannot compile.
pub fn format_build_name(
    persona: &str,
    build_name: &str,
    patch_title: &str,
    statistics_window: &str,
) -> Result<String> {
    let persona = persona.split_whitespace().collect::<Vec<_>>().join(" ");
    if persona.is_empty() {
        return Err(Error::new("Persona must contain visible text"));
    }
    let suffix = format!(" / {statistics_window}");
    let fixed = 6 + suffix.chars().count();
    let persona_budget = MAX_BUILD_NAME_CHARACTERS
        .checked_sub(fixed + 8 + 4)
        .ok_or_else(|| Error::new("Build statistics window exceeds the title limit"))?;
    let prefix = format!("{} | ", truncate(&persona, persona_budget));
    let available = MAX_BUILD_NAME_CHARACTERS - prefix.chars().count() - 3 - suffix.chars().count();
    let build = if build_name.trim().is_empty() {
        "Evidence Default"
    } else {
        build_name.trim()
    };
    let patch = compact_patch_label(if patch_title.trim().is_empty() {
        "Unknown Patch"
    } else {
        patch_title.trim()
    })?;
    let build_budget = build.chars().count().min(
        available
            .saturating_sub(patch.chars().count().min(4))
            .max(8),
    );
    let patch_budget = available
        .checked_sub(build_budget)
        .ok_or_else(|| Error::new("Build title exceeds its character limit"))?;
    Ok(format!(
        "{prefix}{} | {}{suffix}",
        truncate(build, build_budget),
        truncate(&patch, patch_budget)
    ))
}

fn truncate(text: &str, limit: usize) -> String {
    text.chars()
        .take(limit)
        .collect::<String>()
        .trim_end()
        .into()
}

fn compact_patch_label(title: &str) -> Result<String> {
    let pattern = Regex::new(r"([0-9]{1,2})-([0-9]{1,2})-[0-9]{4}")
        .map_err(|error| Error::new(format!("Invalid patch date pattern: {error}")))?;
    for captures in pattern.captures_iter(title) {
        let Some(found) = captures.get(0) else {
            continue;
        };
        if title[..found.start()]
            .chars()
            .next_back()
            .is_some_and(char::is_numeric)
            || title[found.end()..]
                .chars()
                .next()
                .is_some_and(char::is_numeric)
        {
            continue;
        }
        let month = captures
            .get(1)
            .and_then(|value| value.as_str().parse::<u8>().ok());
        let day = captures
            .get(2)
            .and_then(|value| value.as_str().parse::<u8>().ok());
        if let Some((month, day)) = month.zip(day) {
            return Ok(format!("{month:02}{day:02}"));
        }
    }
    Ok(title.into())
}
