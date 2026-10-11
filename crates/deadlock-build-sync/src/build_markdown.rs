use std::fmt::Write as _;

use deadlock_guides::{BuildItem, HeroBuild, HeroBuildCatalog};

/// Renders one hero build as Markdown with the values behind each item.
#[must_use]
pub fn render_build_markdown(build: &HeroBuild, catalog: &HeroBuildCatalog) -> String {
    let mut text = format!("# {}: {}\n\n", build.hero_name, build.title);
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
    if let Some(ability) = &build.key_ability_name {
        let _ = writeln!(text, "Key ability: {ability}.");
    }
    if let Some(item) = build.key_item() {
        let _ = writeln!(
            text,
            "Key item: {} at about {} net worth.\n",
            item.name, build.power_spike_net_worth
        );
    }
    text.push_str("## MAIN CORE (buy from left to right)\n\n");
    write_items(&mut text, &build.core);
    text.push_str("\n## Situational items\n\n");
    write_items(&mut text, &build.situational);
    text
}

fn write_items(text: &mut String, items: &[BuildItem]) {
    text.push_str("| Item | Tier | Cost | Phase | Win rate | Pick rate | Effect | Net worth |\n");
    text.push_str("| --- | --- | --- | --- | --- | --- | --- | --- |\n");
    for item in items {
        let _ = writeln!(
            text,
            "| {} | {} | {} | {} min | {:.1}% | {:.1}% | {:+.3} | {} |",
            item.name,
            item.tier,
            item.cost,
            item.phase_s / 60,
            item.win_rate * 100.0,
            item.adoption * 100.0,
            item.effect,
            item.median_net_worth
        );
    }
}
