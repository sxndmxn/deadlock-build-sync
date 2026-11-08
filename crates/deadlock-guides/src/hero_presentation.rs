use deadlock_data::Result;

use crate::build_text::{
    MAIN_CORE_PANEL, RATES_NOTE, ability_order, evidence, format_soul_window, guide, phase_label,
    play_around, tier_panel_name, variant_note,
};
use crate::build_title::format_build_name;
use crate::hero_build::{BuildItem, HeroBuild, HeroBuildCatalog};
use crate::presentation::{
    BuildPresentation, ManagedTrailer, PresentationAbilities, PresentationCategory,
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
        MAIN_CORE_PANEL,
        &build.core,
        "Buy from left to right.",
        false,
    )?];
    for panel in &build.counters {
        // A narrow panel shows only a short text without covering its items.
        // The panel name states the condition, and the Markdown export states the evidence.
        categories.push(build_category(
            panel.target.panel_name(),
            &panel.items,
            COUNTER_PANEL_TEXT,
            true,
        )?);
    }
    for tier in 1..=4 {
        let items = build
            .situational
            .iter()
            .filter(|item| item.tier == tier)
            .cloned()
            .collect::<Vec<_>>();
        categories.push(build_category(&tier_panel_name(tier), &items, "", true)?);
    }
    let abilities = (!build.ability_ids.is_empty()).then(|| PresentationAbilities {
        ability_ids: build.ability_ids.clone(),
        annotation: if build.variant_id.is_some() {
            format!(
                "Most common complete order among key item owners. n={}.",
                build.ability_matches
            )
        } else {
            format!(
                "Most common complete order at this rank. n={}.",
                build.ability_matches
            )
        },
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
            .map(|item| {
                Ok(PresentationItem {
                    item_id: item.item_id,
                    name: item.name.clone(),
                    annotation: describe_item(item)?,
                    required_flex_slots: None,
                    sell_priority: None,
                    imbue_target_ability_id: item
                        .imbue_target
                        .as_ref()
                        .map(|target| target.ability_id),
                })
            })
            .collect::<Result<_>>()?,
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

/// Shows the game phase, purchase rates with counts, and the soul window.
fn describe_item(item: &BuildItem) -> Result<String> {
    let [win_rate, pick_rate] = item.describe_rates()?;
    Ok(format!(
        "{}\nITEM WIN RATE: {win_rate}\nPICK RATE: {pick_rate}\nSOUL WINDOW: {}",
        phase_label(item.phase_s),
        format_soul_window(item.soul_window)
    ))
}

/// The description of each counter panel. The tests confirmed the effects from 20 minutes.
/// Catalog validation checks that each panel has tested run evidence.
const COUNTER_PANEL_TEXT: &str = "From midgame";

/// Rounds the soul window to whole thousands. The window always spans at least 1k.
fn describe_build(
    build: &HeroBuild,
    catalog: &HeroBuildCatalog,
    snapshot_id: &str,
) -> Result<String> {
    let mut lines = vec![play_around(build)?];
    lines.extend(ability_order(build));
    lines.extend(variant_note(build)?);
    lines.extend([
        guide(!build.counters.is_empty()).into(),
        RATES_NOTE.into(),
        evidence(build, catalog)?,
        String::new(),
        ManagedTrailer {
            path_id: build.path_id(),
            patch_title: catalog.patch.title.clone(),
            snapshot_id: snapshot_id.into(),
        }
        .render(),
    ]);
    Ok(lines.join("\n"))
}
