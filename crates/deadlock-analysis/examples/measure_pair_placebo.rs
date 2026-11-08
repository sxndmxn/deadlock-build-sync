#![forbid(unsafe_code)]

//! Repeats the paired scale test after the alternative agreements move at random.
//!
//! Usage: `cargo run --release --example measure_pair_placebo -- RUN_DIRECTORY BASE_RULE ALTERNATIVE_RULE REPETITIONS`
//!
//! The output is tab-separated text with one z value for each repetition. With correct
//! standard errors, about 5% of the z values are beyond ±2.

use std::path::Path;

use deadlock_analysis::{ExtractionResources, ItemScoring, RunPaths, measure_pair_placebo};
use deadlock_data::{Error, Result};

const USAGE: &str =
    "Usage: measure_pair_placebo RUN_DIRECTORY BASE_RULE ALTERNATIVE_RULE REPETITIONS";

fn main() -> Result<()> {
    let arguments = std::env::args().skip(1).collect::<Vec<_>>();
    let [run, base, alternative, repetitions] = arguments.as_slice() else {
        return Err(Error::new(USAGE));
    };
    let repetitions = repetitions.parse::<u64>().map_err(|_| Error::new(USAGE))?;
    let paths = RunPaths::open(Path::new(run))?;
    let resources = ExtractionResources {
        memory_limit_mb: 12_000,
        threads: 8,
    };
    let seeds = (1..=repetitions).collect::<Vec<_>>();
    println!("seed\tz");
    let z_values = measure_pair_placebo(
        &paths,
        resources,
        base.parse::<ItemScoring>()?,
        alternative.parse::<ItemScoring>()?,
        &seeds,
    )?;
    for (seed, z) in seeds.iter().zip(z_values) {
        println!("{seed}\t{z:.3}");
    }
    Ok(())
}
