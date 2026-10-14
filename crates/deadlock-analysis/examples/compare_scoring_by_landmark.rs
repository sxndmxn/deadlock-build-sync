#![forbid(unsafe_code)]

//! Tests the builds of score rules separately at each test landmark, pooled over heroes.
//!
//! Usage: `cargo run --release --example compare_scoring_by_landmark -- RUN_DIRECTORY SCALE[:FLOOR]...`
//!
//! The output is tab-separated text with one line for each rule and landmark.

use std::path::Path;

use deadlock_analysis::{ExtractionResources, ItemScoring, RunPaths, compare_scoring_by_landmark};
use deadlock_data::{Error, Result};

const USAGE: &str = "Usage: compare_scoring_by_landmark RUN_DIRECTORY SCALE[:FLOOR]...";

fn main() -> Result<()> {
    let arguments = std::env::args().skip(1).collect::<Vec<_>>();
    let [run, rules @ ..] = arguments.as_slice() else {
        return Err(Error::new(USAGE));
    };
    if rules.is_empty() {
        return Err(Error::new(USAGE));
    }
    let rules = rules
        .iter()
        .map(|rule| rule.parse::<ItemScoring>())
        .collect::<Result<Vec<_>>>()?;
    let paths = RunPaths::open(Path::new(run))?;
    let resources = ExtractionResources {
        memory_limit_mb: 12_000,
        threads: 8,
    };
    println!("rule\tlandmark_s\tagreement_coefficient\tstandard_error\tobservations");
    for result in compare_scoring_by_landmark(&paths, resources, &rules)? {
        println!(
            "{}:{}\t{}\t{:.4}\t{:.4}\t{}",
            result.scoring.effect_scale,
            result.scoring.adoption_floor,
            result.landmark_s,
            result.evaluation.agreement_coefficient,
            result.evaluation.standard_error,
            result.evaluation.observations
        );
    }
    Ok(())
}
