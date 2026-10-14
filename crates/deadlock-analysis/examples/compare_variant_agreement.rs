#![forbid(unsafe_code)]

//! Tests whether variant agreement predicts the match result beyond main build agreement.
//!
//! Usage: `cargo run --release --example compare_variant_agreement -- RUN_DIRECTORY`
//!
//! The output is tab-separated text with one line for each agreement coefficient.

use std::path::Path;

use deadlock_analysis::{ExtractionResources, RunPaths, compare_variant_agreement};
use deadlock_data::{Error, Result};

fn main() -> Result<()> {
    let run = std::env::args()
        .nth(1)
        .ok_or_else(|| Error::new("Usage: compare_variant_agreement RUN_DIRECTORY"))?;
    let paths = RunPaths::open(Path::new(&run))?;
    let resources = ExtractionResources {
        memory_limit_mb: 12_000,
        threads: 8,
    };
    let result = compare_variant_agreement(&paths, resources)?;
    println!("agreement\tcoefficient\tstandard_error\tz\theroes\tobservations");
    for (name, value) in [("main", result.main), ("variant", result.variant)] {
        println!(
            "{name}\t{:.4}\t{:.4}\t{:.1}\t{}\t{}",
            value.coefficient,
            value.standard_error,
            value.coefficient / value.standard_error,
            result.heroes,
            result.observations
        );
    }
    Ok(())
}
