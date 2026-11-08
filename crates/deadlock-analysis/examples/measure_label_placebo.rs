#![forbid(unsafe_code)]

//! Repeats the per-hero build tests after the agreements move at random.
//!
//! Usage: `cargo run --release --example measure_label_placebo -- RUN_DIRECTORY REPETITIONS`
//!
//! The output is tab-separated text with one z value per line. With correct standard errors,
//! about 5% of the z values are beyond ±2.

use std::path::Path;

use deadlock_analysis::{ExtractionResources, RunPaths, measure_label_placebo};
use deadlock_data::{Error, Result};

const USAGE: &str = "Usage: measure_label_placebo RUN_DIRECTORY REPETITIONS";

fn main() -> Result<()> {
    let arguments = std::env::args().skip(1).collect::<Vec<_>>();
    let [run, repetitions] = arguments.as_slice() else {
        return Err(Error::new(USAGE));
    };
    let repetitions = repetitions.parse::<u64>().map_err(|_| Error::new(USAGE))?;
    let seeds = (1..=repetitions).collect::<Vec<_>>();
    let paths = RunPaths::open(Path::new(run))?;
    let resources = ExtractionResources {
        memory_limit_mb: 12_000,
        threads: 8,
    };
    println!("z");
    for z in measure_label_placebo(&paths, resources, &seeds)? {
        println!("{z:.3}");
    }
    Ok(())
}
