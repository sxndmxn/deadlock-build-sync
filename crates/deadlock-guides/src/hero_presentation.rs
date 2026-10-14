use deadlock_data::{Error, Rank, RankRange, Result};

use crate::build_title::format_build_name;
use crate::hero_build::{BuildItem, CounterPanel, HeroBuild, HeroBuildCatalog};
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
        describe_item,
    )?];
    for panel in &build.counters {
        categories.push(build_category(
            panel.damage_type.panel_name(),
            &panel.items,
            &describe_counter_panel(panel, catalog)?,
            true,
            describe_item,
        )?);
    }
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
    annotate: fn(&BuildItem) -> Result<String>,
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
            .map(|item| {
                Ok(PresentationItem {
                    item_id: item.item_id,
                    name: item.name.clone(),
                    annotation: annotate(item)?,
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

/// Shows the game phase, purchase rates with counts, and the soul window.
fn describe_item(item: &BuildItem) -> Result<String> {
    let [win_rate, pick_rate] = item.describe_rates()?;
    Ok(format!(
        "{}\nITEM WIN RATE: {win_rate}\nPICK RATE: {pick_rate}\nSOUL WINDOW: {}",
        phase_label(item.phase_s),
        format_soul_window(item.soul_window)
    ))
}

/// States when to use a counter panel and the weakest phase result of its run test.
fn describe_counter_panel(panel: &CounterPanel, catalog: &HeroBuildCatalog) -> Result<String> {
    let evidence = catalog
        .counter_evidence
        .iter()
        .find(|evidence| evidence.damage_type == panel.damage_type)
        .ok_or_else(|| Error::new("Counter panel has no run evidence"))?;
    let label = panel.damage_type.label();
    Ok(format!(
        "From mid game, when most enemy damage is {label} damage. These items won more against {label}-heavy teams on 4 tested patches. This patch: z ≥ {:.1}.",
        evidence.minimum_z()
    ))
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
    if build.variant_id.is_some() {
        lines.push(format!(
            "Item choices use {} player matches with {} at 20 or 30 minutes.",
            build.observations, key_item.name
        ));
    }
    let guide = if build.counters.is_empty() {
        "Buy MAIN CORE from left to right. TIER items are situational choices."
    } else {
        "Buy MAIN CORE from left to right. VS panels answer the main enemy damage type. TIER items are situational choices."
    };
    lines.extend([
        guide.into(),
        "Item rates count each buyer once per match across this hero's ranked matches. They do not measure the complete build.".into(),
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
