#![forbid(unsafe_code)]

//! Reports the gate result of every candidate key item for additional builds.
//!
//! Usage: `cargo run --release --example explain_variant_candidates -- RUN_DIRECTORY [SEPARATION [DISTINCT_ITEMS]]`
//!
//! The output is tab-separated text with one line for each hero and Tier 3 or Tier 4 item.
//! The `gate` column names the first development gate that rejected the item, or `selected`.
//! The `production_gate` column repeats the production check for selected items.

use std::path::Path;

use deadlock_analysis::{
    DEFAULT_VARIANT_SELECTION, ExtractionResources, RunPaths, VariantGate,
    explain_variant_candidates,
};
use deadlock_data::{Error, Result};

fn main() -> Result<()> {
    let mut arguments = std::env::args().skip(1);
    let run = arguments.next().ok_or_else(|| {
        Error::new("Usage: explain_variant_candidates RUN_DIRECTORY [SEPARATION [DISTINCT_ITEMS]]")
    })?;
    let mut rule = DEFAULT_VARIANT_SELECTION;
    if let Some(text) = arguments.next() {
        rule.minimum_separation = text
            .parse::<f64>()
            .ok()
            .filter(|value| (0.0..=1.0).contains(value))
            .ok_or_else(|| Error::new("Separation must be a number from 0 to 1"))?;
    }
    if let Some(text) = arguments.next() {
        rule.minimum_distinct_items = text
            .parse::<usize>()
            .ok()
            .filter(|value| *value >= 1)
            .ok_or_else(|| Error::new("Distinct items must be a positive integer"))?;
    }
    let paths = RunPaths::open(Path::new(&run))?;
    let resources = ExtractionResources {
        memory_limit_mb: 12_000,
        threads: 8,
    };
    println!(
        "hero_id\titem_id\titem_name\ttier\tcost\tadoption_20\tadoption_30\teffect_20\teffect_30\towners\tseparation_main\tseparation_minimum\tgate\tproduction_gate"
    );
    for report in explain_variant_candidates(&paths, resources, rule)? {
        let candidate = &report.development;
        println!(
            "{}\t{}\t{}\t{}\t{}\t{:.3}\t{:.3}\t{:.4}\t{:.4}\t{}\t{}\t{}\t{}\t{}",
            report.hero_id,
            report.item.item_id,
            report.item.item_name,
            report.item.tier,
            report.item.cost,
            candidate.adoption[0],
            candidate.adoption[1],
            candidate.effect[0],
            candidate.effect[1],
            candidate.owners,
            format_separation(candidate.separation_main),
            format_separation(candidate.separation_minimum),
            candidate.gate.name(),
            report.production.map_or("", VariantGate::name),
        );
    }
    Ok(())
}

fn format_separation(value: Option<f64>) -> String {
    value.map_or_else(String::new, |value| format!("{value:.3}"))
}
