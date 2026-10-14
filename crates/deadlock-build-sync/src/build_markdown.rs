use std::fmt::Write as _;

use deadlock_data::Result;
use deadlock_guides::{BuildItem, HeroBuild, HeroBuildCatalog};

/// Renders one hero build as Markdown with the values behind each item.
///
/// # Errors
/// Returns an error when item purchase counts are invalid.
pub fn render_build_markdown(build: &HeroBuild, catalog: &HeroBuildCatalog) -> Result<String> {
    let mut text = format!("# {}\n\n", build.title);
    let evaluation = &build.evaluation;
    let _ = writeln!(
        text,
        "Evidence: {} (agreement coefficient {:+.2} ± {:.2}, held-out observations {}).",
        evaluation.confidence.label(),
        evaluation.agreement_coefficient,
        evaluation.standard_error,
        evaluation.observations
    );
    let _ = writeln!(
        text,
        "Matches: {} to {}, badges {}–{}, client {}.\n",
        catalog.cohort.since,
        catalog.cohort.as_of,
        catalog.cohort.minimum_badge,
        catalog.cohort.maximum_badge,
        catalog.client_version
    );
    if let Some(focus) = &build.ability_focus {
        let _ = writeln!(text, "Ability focus: {}.", focus.name);
    }
    if let Some(ability) = &build.key_ability_name {
        let _ = writeln!(text, "Ability order: max {ability} first.");
    }
    if let Some(item) = build.key_item() {
        let _ = writeln!(
            text,
            "Key item: {} at about {} net worth.\n",
            item.name, build.power_spike_net_worth
        );
        if build.variant_id.is_some() {
            let _ = writeln!(
                text,
                "Item choices use {} player matches with {} at 20 or 30 minutes.\n",
                build.observations, item.name
            );
        }
    }
    text.push_str("Item rates use all selected ranked matches for this hero, regardless of build or purchase time.\n");
    text.push_str(
        "Win rate shows wins / buyer matches. Pick rate shows buyer matches / hero matches.\n",
    );
    text.push_str("Each player match counts once per item. These rates do not measure the complete build or prove an item causes wins.\n\n");
    text.push_str("## MAIN CORE (buy from left to right)\n\n");
    write_items(&mut text, &build.core)?;
    text.push_str("\n## Situational items\n\n");
    write_items(&mut text, &build.situational)?;
    Ok(text)
}

fn write_items(text: &mut String, items: &[BuildItem]) -> Result<()> {
    text.push_str(
        "| Item | Tier | Cost | Phase | Item win rate (wins/buyers) | Pick rate (buyers/hero matches) | Soul window | Effect | Net worth |\n",
    );
    text.push_str("| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n");
    for item in items {
        let [win_rate, pick_rate] = item.describe_rates()?;
        let _ = writeln!(
            text,
            "| {} | {} | {} | {} min | {win_rate} | {pick_rate} | {}–{} | {:+.3} | {} |",
            item.name,
            item.tier,
            item.cost,
            item.phase_s / 60,
            item.soul_window[0],
            item.soul_window[1],
            item.effect,
            item.median_net_worth
        );
    }
    Ok(())
}
