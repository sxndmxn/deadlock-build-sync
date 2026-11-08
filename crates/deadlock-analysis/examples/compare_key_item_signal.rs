#![forbid(unsafe_code)]

//! Tests whether owning the key item predicts the match result beyond CORE agreement.
//!
//! Usage: `cargo run --release --example compare_key_item_signal -- RUN_DIRECTORY`
//!
//! The output is tab-separated text with one line for each coefficient.

use std::path::Path;

use deadlock_analysis::{ExtractionResources, RunPaths, compare_key_item_signal};
use deadlock_data::{Error, Result};

fn main() -> Result<()> {
    let run = std::env::args()
        .nth(1)
        .ok_or_else(|| Error::new("Usage: compare_key_item_signal RUN_DIRECTORY"))?;
    let paths = RunPaths::open(Path::new(&run))?;
    let resources = ExtractionResources {
        memory_limit_mb: 12_000,
        threads: 8,
    };
    let result = compare_key_item_signal(&paths, resources)?;
    println!("value\tcoefficient\tstandard_error\tz\theroes\tobservations");
    for (name, value) in [("core", result.base), ("key_item", result.alternative)] {
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
