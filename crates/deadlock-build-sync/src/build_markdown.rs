use std::fmt::Write as _;

use deadlock_data::Result;
use deadlock_guides::{
    BuildItem, HeroBuild, HeroBuildCatalog, MAIN_CORE_PANEL, ability_order, evidence,
    format_soul_window, phase_label, play_around, rank_label, variant_note,
};

/// Renders one hero build as Markdown with the values behind each item.
///
/// The sentences are the sentences of the Steam description. The tables add the numbers
/// behind them.
///
/// # Errors
/// Returns an error when item purchase counts are invalid.
pub fn render_build_markdown(build: &HeroBuild, catalog: &HeroBuildCatalog) -> Result<String> {
    let mut text = format!("# {}\n\n", build.title);
    let evaluation = &build.evaluation;
    let _ = writeln!(text, "{}", evidence(build, catalog)?);
    let _ = writeln!(
        text,
        "Agreement coefficient {:+.2} ± {:.2} on {} held-out observations.",
        evaluation.agreement_coefficient, evaluation.standard_error, evaluation.observations
    );
    if let Some(hero) = &evaluation.hero_estimate {
        let _ = writeln!(
            text,
            "The label uses the test pooled with comparable builds of all heroes. This build alone: {:+.2} ± {:.2}.",
            hero.agreement_coefficient, hero.standard_error
        );
    }
    let _ = writeln!(
        text,
        "Matches: {} to {}, {}, client {}.\n",
        catalog.cohort.since,
        catalog.cohort.as_of,
        rank_label(catalog)?,
        catalog.client_version
    );
    let _ = writeln!(text, "{}", play_around(build)?);
    if let Some(focus) = &build.ability_focus {
        let _ = writeln!(text, "Ability focus: {}.", focus.name);
    }
    if let Some(sentence) = ability_order(build) {
        let _ = writeln!(text, "{sentence}");
    }
    if let Some(sentence) = variant_note(build)? {
        let _ = writeln!(text, "{sentence}");
    }
    text.push_str("\nItem rates use all selected ranked matches for this hero, regardless of build or purchase time.\n");
    text.push_str(
        "Win rate shows wins / buyer matches. Pick rate shows buyer matches / hero matches.\n",
    );
    text.push_str("Each player match counts once per item. These rates do not measure the complete build or prove an item causes wins.\n\n");
    let _ = writeln!(text, "## {MAIN_CORE_PANEL} (buy from left to right)\n");
    write_items(&mut text, &build.core)?;
    for panel in &build.counters {
        let label = panel.target.label();
        let _ = writeln!(
            text,
            "\n## {} (from mid game, when {})\n",
            panel.target.panel_name(),
            panel.target.condition()
        );
        if let Some(evidence) = catalog
            .counter_evidence
            .iter()
            .find(|evidence| evidence.target == panel.target)
        {
            for phase in &evidence.phases {
                let _ = writeln!(
                    text,
                    "Counter test at {} min: {:+.3} ± {:.3} log-odds per item and standard deviation of the enemy {label} condition (n={}).",
                    phase.phase_s / 60,
                    phase.coefficient,
                    phase.standard_error,
                    phase.observations
                );
            }
            text.push('\n');
        }
        write_items(&mut text, &panel.items)?;
    }
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
            "| {} | {} | {} | {} | {win_rate} | {pick_rate} | {} | {:+.3} | {} |",
            item.name,
            item.tier,
            item.cost,
            phase_label(item.phase_s),
            format_soul_window(item.soul_window),
            item.effect,
            item.median_net_worth
        );
    }
    Ok(())
}
