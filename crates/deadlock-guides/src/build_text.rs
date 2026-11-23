//! The sentences and number formats that describe a build.
//!
//! The Steam description and the Markdown export render the same build. Both take their
//! sentences from here, so a change of wording lands in one place.

use deadlock_data::{Error, Rank, RankRange, Result};

use crate::build_title::MAX_BUILD_NAME_CHARACTERS;
use crate::hero_build::{HeroBuild, HeroBuildCatalog, log_odds_to_win_points};

/// The first panel of every build.
pub const MAIN_CORE_PANEL: &str = "MAIN CORE";

/// The situational panel of one shop tier.
#[must_use]
pub fn tier_panel_name(tier: u8) -> String {
    format!("TIER {tier}")
}

/// The note on the item rates. The rates count buyers, not the complete build.
pub const RATES_NOTE: &str = "Item rates count each buyer once per match across this hero's ranked matches. They do not measure the complete build.";

/// The sentence that names the ability focus, the key item, and the power spike.
///
/// # Errors
/// Returns an error when the key item is not in CORE.
pub fn play_around(build: &HeroBuild) -> Result<String> {
    let key_item = build
        .key_item()
        .ok_or_else(|| Error::new("Build key item is not in CORE"))?;
    let focus = build.ability_focus.as_ref().map_or_else(
        || key_item.name.clone(),
        |focus| format!("{} with {}", focus.name, key_item.name),
    );
    Ok(format!(
        "Play around: {focus} at about {} net worth.",
        format_souls(build.power_spike_net_worth)
    ))
}

/// The sentence that names the first ability to upgrade to the maximum, when known.
#[must_use]
pub fn ability_order(build: &HeroBuild) -> Option<String> {
    build
        .key_ability_name
        .as_ref()
        .map(|ability| format!("Ability order: max {ability} first."))
}

/// The sentence that states the owner matches of an additional build.
///
/// # Errors
/// Returns an error when the key item is not in CORE.
pub fn variant_note(build: &HeroBuild) -> Result<Option<String>> {
    if build.variant_id.is_none() {
        return Ok(None);
    }
    let key_item = build
        .key_item()
        .ok_or_else(|| Error::new("Build key item is not in CORE"))?;
    Ok(Some(format!(
        "Item choices use {} player matches with {} at 20 or 30 minutes.",
        build.observations, key_item.name
    )))
}

/// The start of the title of the BEST build of a hero with several builds.
pub const BEST_TITLE_PREFIX: &str = "BEST ";

/// Returns the build title, with the BEST mark when the build is the BEST build of its hero.
///
/// When the mark and the title exceed the title limit, the marked title names the key item only.
#[must_use]
pub fn display_title(build: &HeroBuild, catalog: &HeroBuildCatalog) -> String {
    if !build.is_best(catalog) {
        return build.title.clone();
    }
    std::iter::once(build.title.as_str())
        .chain(build.key_item().map(|item| item.name.as_str()))
        .map(|title| format!("{BEST_TITLE_PREFIX}{title}"))
        .find(|title| title.chars().count() <= MAX_BUILD_NAME_CHARACTERS)
        .unwrap_or_else(|| build.title.clone())
}

/// The sentence that states the result of the held-out test against the main build of the hero.
///
/// The sentence states the result only. The Markdown export adds the numbers. A hero with one
/// build has no sentence.
#[must_use]
pub fn main_comparison(build: &HeroBuild, catalog: &HeroBuildCatalog) -> Option<String> {
    let several = catalog
        .heroes
        .iter()
        .filter(|other| other.hero_id == build.hero_id)
        .nth(1)
        .is_some();
    if build.variant_id.is_none() {
        return several.then(|| {
            if build.is_best(catalog) {
                "BEST: no additional build of this hero tested better than this main build.".into()
            } else {
                "An additional build of this hero tested better than this main build.".into()
            }
        });
    }
    let Some(contrast) = &build.main_contrast else {
        return Some("Not tested against the main build: too few test matches.".into());
    };
    Some(if !contrast.is_better() {
        "Tested against the main build: no clear difference.".into()
    } else if build.is_best(catalog) {
        "BEST: tested better than the main build.".into()
    } else {
        "Tested better than the main build.".into()
    })
}

/// The sentence that states the approximate win rate difference of players with the build,
/// against players without it, at equal net worth.
///
/// The value uses the label estimate of the held-out test. It is an association, not a cause.
/// An untested build has no sentence.
#[must_use]
pub fn win_rate(build: &HeroBuild) -> Option<String> {
    (build.evaluation.standard_error > 0.0).then(|| {
        format!(
            "Win rate difference at equal net worth: about {:+.1} points.",
            log_odds_to_win_points(build.evaluation.agreement_coefficient)
        )
    })
}

/// The instruction that tells the player how to read the panels.
#[must_use]
pub const fn guide(has_counters: bool) -> &'static str {
    if has_counters {
        "Buy MAIN CORE from left to right. VS panels answer the enemy team. TIER items are situational choices."
    } else {
        "Buy MAIN CORE from left to right. TIER items are situational choices."
    }
}

/// The evidence sentence: the confidence label, the test, the rank range, and the match window.
///
/// # Errors
/// Returns an error when the cohort has an invalid badge or timestamp.
pub fn evidence(build: &HeroBuild, catalog: &HeroBuildCatalog) -> Result<String> {
    let [since, as_of] = catalog.cohort.dates()?;
    Ok(format!(
        "Evidence: {} ({}, n={}). Ranked • {} • {since} to {as_of}.",
        build.evaluation.confidence.label(),
        if build.evaluation.hero_estimate.is_some() {
            "held-out test pooled with all heroes"
        } else {
            "held-out test"
        },
        build.evaluation.observations,
        rank_label(catalog)?
    ))
}

/// The rank range of the catalog as text, for example `Ritualist I–Eternus V`.
///
/// # Errors
/// Returns an error when a badge is not a rank.
pub fn rank_label(catalog: &HeroBuildCatalog) -> Result<String> {
    Ok(RankRange {
        minimum: Rank::try_from(catalog.cohort.minimum_badge)?,
        maximum: Rank::try_from(catalog.cohort.maximum_badge)?,
    }
    .label())
}

/// The game phase of a landmark time: early game to 10 minutes, mid game to 25 minutes.
#[must_use]
pub const fn phase_label(phase_s: u32) -> &'static str {
    match phase_s {
        0..=600 => "EARLY GAME",
        601..=1500 => "MID GAME",
        _ => "LATE GAME",
    }
}

/// Souls in thousands, for example `18k`. Values below 1000 stay exact.
#[must_use]
pub fn format_souls(value: u32) -> String {
    if value >= 1000 {
        format!("{}k", (value + 500) / 1000)
    } else {
        value.to_string()
    }
}

/// A net worth range in thousands, for example `8k-16k`. The upper bound is above the lower.
#[must_use]
pub fn format_soul_window([lower, upper]: [u32; 2]) -> String {
    let lower = (lower + 500) / 1000;
    let upper = ((upper + 500) / 1000).max(lower + 1);
    format!("{lower}k-{upper}k")
}
