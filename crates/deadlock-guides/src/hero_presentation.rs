use deadlock_data::{Error, Rank, RankRange, Result};

use crate::build_title::format_build_name;
use crate::hero_build::{BuildItem, HeroBuild, HeroBuildCatalog};
use crate::presentation::{
    BuildPresentation, MANAGED_MARKER, PresentationAbilities, PresentationCategory,
    PresentationContent, PresentationItem,
};

// The game command Compact All gave these sizes to installed builds on 2026-11-01.
const MAXIMUM_COLUMNS: usize = 6;
const ITEM_COLUMN_WIDTH: f32 = 81.75;
const CATEGORY_SIDE_PADDING: f32 = 12.0;
const MINIMUM_CATEGORY_WIDTH: f32 = 100.0;
const ITEM_ROW_HEIGHT: f32 = 120.0;
const CATEGORY_HEADER_HEIGHT: f32 = 42.75;
const EMPTY_WIDTH: f32 = 256.0;
const EMPTY_HEIGHT: f32 = 56.0;

/// Converts one hero build to the Steam presentation.
///
/// MAIN CORE holds the purchase order from left to right. TIER 1 to TIER 4 hold
/// situational items for the matching shop tier.
///
/// # Errors
/// Returns an error when the build violates the Steam presentation contract.
pub fn build_hero_presentation(
    build: &HeroBuild,
    catalog: &HeroBuildCatalog,
    snapshot_id: &str,
    persona: &str,
) -> Result<BuildPresentation> {
    let mut categories = vec![build_category(
        "MAIN CORE",
        &build.core,
        "Buy from left to right.",
        false,
        describe_item,
    )?];
    for tier in 1..=4 {
        let items = build
            .situational
            .iter()
            .filter(|item| item.tier == tier)
            .cloned()
            .collect::<Vec<_>>();
        categories.push(build_category(
            &format!("TIER {tier}"),
            &items,
            "",
            true,
            describe_item,
        )?);
    }
    let abilities = (!build.ability_ids.is_empty()).then(|| PresentationAbilities {
        ability_ids: build.ability_ids.clone(),
        annotation: format!(
            "Most common complete order at this rank. n={}.",
            build.ability_matches
        ),
    });
    BuildPresentation::new(PresentationContent {
        hero_id: build.hero_id,
        name: format_build_name(persona, &build.title)?,
        tag_ids: build.tag_ids,
        description: describe_build(build, catalog, snapshot_id)?,
        categories,
        abilities,
    })
}

fn build_category(
    name: &str,
    items: &[BuildItem],
    description: &str,
    optional: bool,
    annotate: fn(&BuildItem) -> String,
) -> Result<PresentationCategory> {
    let (width, height) = compact_category_size(items.len())?;
    Ok(PresentationCategory {
        name: name.into(),
        description: description.into(),
        width,
        height,
        optional,
        items: items
            .iter()
            .map(|item| PresentationItem {
                item_id: item.item_id,
                name: item.name.clone(),
                annotation: annotate(item),
                required_flex_slots: None,
                sell_priority: None,
                imbue_target_ability_id: item.imbue_target.as_ref().map(|target| target.ability_id),
            })
            .collect(),
    })
}

/// Returns the width and height that the game command Compact All gives a category.
///
/// The game uses the fewest rows of at most six items.
/// It then uses the fewest columns that hold the items in those rows.
fn compact_category_size(item_count: usize) -> Result<(f32, f32)> {
    if item_count == 0 {
        return Ok((EMPTY_WIDTH, EMPTY_HEIGHT));
    }
    let rows = item_count.div_ceil(MAXIMUM_COLUMNS);
    let columns = item_count.div_ceil(rows);
    let width = ITEM_COLUMN_WIDTH
        .mul_add(f32::from(u16::try_from(columns)?), CATEGORY_SIDE_PADDING)
        .max(MINIMUM_CATEGORY_WIDTH);
    let height = ITEM_ROW_HEIGHT.mul_add(f32::from(u16::try_from(rows)?), CATEGORY_HEADER_HEIGHT);
    Ok((width, height))
}

/// Shows the game phase, the win rate of owners, the pick rate, and the soul window, one per line.
fn describe_item(item: &BuildItem) -> String {
    format!(
        "{}\nWIN RATE: {}\nPICK RATE: {}\nSOUL WINDOW: {}",
        phase_label(item.phase_s),
        format_share(item.win_rate),
        format_share(item.adoption),
        format_soul_window(item.soul_window)
    )
}

/// Rounds the soul window to whole thousands. The window always spans at least 1k.
fn format_soul_window([lower, upper]: [u32; 2]) -> String {
    let lower = (lower + 500) / 1000;
    let upper = ((upper + 500) / 1000).max(lower + 1);
    format!("{lower}k-{upper}k")
}

fn describe_build(
    build: &HeroBuild,
    catalog: &HeroBuildCatalog,
    snapshot_id: &str,
) -> Result<String> {
    let key_item = build
        .key_item()
        .ok_or_else(|| Error::new("Build key item is not in CORE"))?;
    let focus = build.ability_focus.as_ref().map_or_else(
        || key_item.name.clone(),
        |focus| format!("{} with {}", focus.name, key_item.name),
    );
    let ranks = RankRange {
        minimum: Rank::try_from(catalog.cohort.minimum_badge)?,
        maximum: Rank::try_from(catalog.cohort.maximum_badge)?,
    };
    let patch_title = text_field(catalog, "title");
    let mut lines = vec![format!(
        "Play around: {focus} at about {} net worth.",
        format_souls(build.power_spike_net_worth)
    )];
    if let Some(ability) = &build.key_ability_name {
        lines.push(format!("Ability order: max {ability} first."));
    }
    lines.extend([
        "Buy MAIN CORE from left to right. TIER items are situational choices.".into(),
        format!(
            "Evidence: {} (held-out test, n={}). Ranked • {} • {} to {}.",
            build.evaluation.confidence.label(),
            build.evaluation.observations,
            ranks.label(),
            catalog.cohort.since.get(..10).unwrap_or_default(),
            catalog.cohort.as_of.get(..10).unwrap_or_default()
        ),
        String::new(),
        MANAGED_MARKER.into(),
        format!("Build path: {}.", build.path_id()),
        format!("Patch: {patch_title}."),
        format!("Snapshot: {snapshot_id}."),
    ]);
    Ok(lines.join("\n"))
}

fn text_field<'catalog>(catalog: &'catalog HeroBuildCatalog, name: &str) -> &'catalog str {
    catalog
        .patch
        .get(name)
        .and_then(serde_json::Value::as_str)
        .unwrap_or_default()
}

const fn phase_label(phase_s: u32) -> &'static str {
    match phase_s {
        0..=600 => "EARLY GAME",
        601..=1500 => "MID GAME",
        _ => "LATE GAME",
    }
}

fn format_souls(value: u32) -> String {
    if value >= 1000 {
        format!("{}k", (value + 500) / 1000)
    } else {
        value.to_string()
    }
}

fn format_share(share: f64) -> String {
    format!("{:.1}%", share * 100.0)
}
