#![forbid(unsafe_code)]

//! Tests builds that use only the earliest fraction of the development matches.
//!
//! Usage: `cargo run --release --example compare_training_fractions -- RUN_DIRECTORY FRACTION...`
//!
//! The output is tab-separated text with one line for each fraction.

use std::path::Path;

use deadlock_analysis::{ExtractionResources, RunPaths, compare_training_fractions};
use deadlock_data::{Error, Result};

const USAGE: &str = "Usage: compare_training_fractions RUN_DIRECTORY FRACTION...";

fn main() -> Result<()> {
    let arguments = std::env::args().skip(1).collect::<Vec<_>>();
    let [run, fractions @ ..] = arguments.as_slice() else {
        return Err(Error::new(USAGE));
    };
    let fractions = fractions
        .iter()
        .map(|value| value.parse::<f64>().map_err(|_| Error::new(USAGE)))
        .collect::<Result<Vec<_>>>()?;
    let paths = RunPaths::open(Path::new(run))?;
    let resources = ExtractionResources {
        memory_limit_mb: 12_000,
        threads: 8,
    };
    println!("fraction\tdevelopment_matches\tagreement_coefficient\tstandard_error\tobservations");
    for result in compare_training_fractions(&paths, resources, &fractions)? {
        println!(
            "{}\t{}\t{:.4}\t{:.4}\t{}",
            result.fraction,
            result.matches,
            result.evaluation.agreement_coefficient,
            result.evaluation.standard_error,
            result.evaluation.observations
        );
    }
    Ok(())
}
