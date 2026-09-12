use std::sync::LazyLock;

use deadlock_data::{Error, Result};
use regex_lite::Regex;

struct Patterns {
    resistance_prefix: Regex,
    resistance_suffix: Regex,
    control_immunity: Regex,
    defensive_prefix: Regex,
    defensive_suffix: Regex,
    ally_target: Regex,
}

static PATTERNS: LazyLock<Result<Patterns>> = LazyLock::new(|| {
    Ok(Patterns {
        resistance_prefix: compile(
            r"\b(reduce|reduces|reduced|reduction|lower|lowers|lowered|remove|removes|enemy|enemies)\b",
        )?,
        resistance_suffix: compile(r"\b(reduction|shred)\b")?,
        control_immunity: compile(r"\bimmune\b[^.!?]{0,96}\b(stun|silence|sleep|root|disarm)\b")?,
        defensive_prefix: compile(r"\b(immune|immunity|resistant|resistance)\b[^.!?]{0,96}$")?,
        defensive_suffix: compile(r"^\s+(?:immunity|resistance)\b")?,
        ally_target: compile(r"\bally\b|\bfriendly target\b")?,
    })
});

fn compile(pattern: &str) -> Result<Regex> {
    Regex::new(pattern).map_err(|error| Error::new(format!("Invalid mechanics pattern: {error}")))
}

fn patterns() -> Result<&'static Patterns> {
    PATTERNS
        .as_ref()
        .map_err(|error| Error::new(error.to_string()))
}

pub fn positive_resistance(text: &str, phrase: &str) -> Result<bool> {
    let patterns = patterns()?;
    Ok(text.match_indices(phrase).any(|(index, found)| {
        let prefix = preceding_characters(&text[..index], 48);
        let suffix = following_characters(&text[index + found.len()..], 24);
        !patterns.resistance_prefix.is_match(prefix) && !patterns.resistance_suffix.is_match(suffix)
    }))
}

pub fn control_immunity(text: &str) -> Result<bool> {
    Ok(text.contains("suppress negative status effects")
        || patterns()?.control_immunity.is_match(text))
}

pub fn offensive_response(text: &str, phrase: &str) -> Result<bool> {
    let patterns = patterns()?;
    Ok(text.match_indices(phrase).any(|(index, found)| {
        let prefix = preceding_characters(&text[..index], 96);
        let suffix = following_characters(&text[index + found.len()..], 24);
        !(patterns.defensive_prefix.is_match(prefix)
            || phrase == "movement slow" && patterns.defensive_suffix.is_match(suffix))
    }))
}

pub fn ally_target(text: &str) -> Result<bool> {
    Ok(patterns()?.ally_target.is_match(text))
}

fn preceding_characters(text: &str, count: usize) -> &str {
    let offset = text
        .char_indices()
        .rev()
        .nth(count.saturating_sub(1))
        .map_or(0, |(index, _)| index);
    &text[offset..]
}

fn following_characters(text: &str, count: usize) -> &str {
    &text[..text
        .char_indices()
        .nth(count)
        .map_or(text.len(), |(index, _)| index)]
}
