#![forbid(unsafe_code)]

//! Tests each hero's main build on two halves of the held-out test matches.
//!
//! Usage: `cargo run --release --example measure_label_halves -- RUN_DIRECTORY`
//!
//! The output is tab-separated text with one line for each hero.

use std::path::Path;

use deadlock_analysis::{ExtractionResources, RunPaths, measure_label_halves};
use deadlock_data::{Error, Result};

fn main() -> Result<()> {
    let run = std::env::args()
        .nth(1)
        .ok_or_else(|| Error::new("Usage: measure_label_halves RUN_DIRECTORY"))?;
    let paths = RunPaths::open(Path::new(&run))?;
    let resources = ExtractionResources {
        memory_limit_mb: 12_000,
        threads: 8,
    };
    println!(
        "hero_id\teven_coefficient\teven_standard_error\teven_label\todd_coefficient\todd_standard_error\todd_label"
    );
    for halves in measure_label_halves(&paths, resources)? {
        println!(
            "{}\t{:.4}\t{:.4}\t{}\t{:.4}\t{:.4}\t{}",
            halves.hero_id,
            halves.even.agreement_coefficient,
            halves.even.standard_error,
            halves.even.confidence.label(),
            halves.odd.agreement_coefficient,
            halves.odd.standard_error,
            halves.odd.confidence.label()
        );
    }
    Ok(())
}
