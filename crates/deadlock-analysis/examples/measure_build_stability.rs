#![forbid(unsafe_code)]

//! Compares builds from the earlier and the later half of the development matches.
//!
//! Usage: `cargo run --release --example measure_build_stability -- RUN_DIRECTORY [SCALE[:FLOOR]]`
//!
//! The output is tab-separated text with one line for each hero.

use std::path::Path;

use deadlock_analysis::{
    DEFAULT_SCORING, ExtractionResources, ItemScoring, RunPaths, measure_build_stability,
};
use deadlock_data::{Error, Result};

fn main() -> Result<()> {
    let mut arguments = std::env::args().skip(1);
    let run = arguments.next().ok_or_else(|| {
        Error::new("Usage: measure_build_stability RUN_DIRECTORY [SCALE[:FLOOR]]")
    })?;
    let scoring = arguments
        .next()
        .map_or(Ok(DEFAULT_SCORING), |rule| rule.parse::<ItemScoring>())?;
    let paths = RunPaths::open(Path::new(&run))?;
    let resources = ExtractionResources {
        memory_limit_mb: 12_000,
        threads: 8,
    };
    println!("hero_id\tcore_overlap\tsame_key_item");
    for result in measure_build_stability(&paths, resources, scoring)? {
        println!(
            "{}\t{:.3}\t{}",
            result.hero_id, result.core_overlap, result.same_key_item
        );
    }
    Ok(())
}
