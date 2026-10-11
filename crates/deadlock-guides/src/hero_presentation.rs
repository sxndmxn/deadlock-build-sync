use deadlock_data::{Error, Rank, RankRange, Result};

use crate::build_title::format_build_name;
use crate::hero_build::{BuildItem, HeroBuild, HeroBuildCatalog};
use crate::presentation::{
    BuildPresentation, MANAGED_MARKER, PresentationAbilities, PresentationCategory,
    PresentationContent, PresentationItem,
};

const CATEGORY_COLUMNS: usize = 6;
const COLUMN_WIDTH: f32 = 90.0;
const PANEL_PADDING: f32 = 24.0;
const FIRST_ROW_HEIGHT: f32 = 185.0;
const NEXT_ROW_HEIGHT: f32 = 129.0;
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
        describe_core_item,
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
            describe_situational_item,
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
    let (width, height) = if items.is_empty() {
        (EMPTY_WIDTH, EMPTY_HEIGHT)
    } else {
        let columns = items.len().min(CATEGORY_COLUMNS);
        let rows = items.len().div_ceil(CATEGORY_COLUMNS);
        (
            COLUMN_WIDTH.mul_add(f32::from(u16::try_from(columns)?), PANEL_PADDING),
            NEXT_ROW_HEIGHT.mul_add(f32::from(u16::try_from(rows - 1)?), FIRST_ROW_HEIGHT),
        )
    };
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
                imbue_target_ability_id: None,
            })
            .collect(),
    })
}

fn describe_core_item(item: &BuildItem) -> String {
    format!(
        "{}. Usually bought at about {} net worth. {} of players own it.",
        phase_label(item.phase_s),
        format_souls(item.median_net_worth),
        format_share(item.adoption)
    )
}

fn describe_situational_item(item: &BuildItem) -> String {
    format!(
        "Situational. Wins more than other choices in similar {} states. {} of players own it.",
        phase_label(item.phase_s).to_lowercase(),
        format_share(item.adoption)
    )
}

fn describe_build(
    build: &HeroBuild,
    catalog: &HeroBuildCatalog,
    snapshot_id: &str,
) -> Result<String> {
    let key_item = build
        .key_item()
        .ok_or_else(|| Error::new("Build key item is not in CORE"))?;
    let mut focus = Vec::new();
    if let Some(ability) = &build.key_ability_name {
        focus.push(format!("max {ability} first"));
    }
    focus.push(format!(
        "get {} for the power spike at about {} net worth",
        key_item.name,
        format_souls(build.power_spike_net_worth)
    ));
    let ranks = RankRange {
        minimum: Rank::try_from(catalog.cohort.minimum_badge)?,
        maximum: Rank::try_from(catalog.cohort.maximum_badge)?,
    };
    let patch_title = text_field(catalog, "title");
    let lines = [
        format!("Play around: {}.", focus.join(", then ")),
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
    ];
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
        0..=600 => "Lane",
        601..=1500 => "Mid game",
        _ => "Late game",
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
    format!("{:.0}%", share * 100.0)
}
