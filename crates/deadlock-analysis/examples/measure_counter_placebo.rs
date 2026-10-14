#![forbid(unsafe_code)]

//! Repeats the counter test after the team conditions are moved to other teams at random.
//!
//! Usage: `cargo run --release --example measure_counter_placebo -- RUN_DIRECTORY REPETITIONS`
//!
//! The output is tab-separated text with one line for each z value. With correct standard
//! errors, about 5% of the z values are beyond ±2.

use std::path::Path;

use deadlock_analysis::{ExtractionResources, RunPaths, measure_counter_placebo};
use deadlock_data::{Error, Result};

const USAGE: &str = "Usage: measure_counter_placebo RUN_DIRECTORY REPETITIONS";

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
    println!("seed\tphase_s\tterm\tz");
    for result in measure_counter_placebo(&paths, resources, &seeds)? {
        for (term, z) in result.z_values.iter().enumerate() {
            println!("{}\t{}\t{term}\t{z:.3}", result.seed, result.phase_s);
        }
    }
    Ok(())
}
