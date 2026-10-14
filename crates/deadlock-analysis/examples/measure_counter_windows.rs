#![forbid(unsafe_code)]

//! Measures the counter item groups in time windows of one extracted run.
//!
//! Usage: `cargo run --release --example measure_counter_windows -- RUN_DIRECTORY WINDOWS`
//!
//! The output is tab-separated text with one line for each window, group, and phase.
//! A positive coefficient means that the group wins more against its damage type.

use std::path::Path;

use deadlock_analysis::{ExtractionResources, RunPaths, measure_counter_windows};
use deadlock_data::{Error, Result};

const USAGE: &str = "Usage: measure_counter_windows RUN_DIRECTORY WINDOWS [hero-terms]";

fn main() -> Result<()> {
    let arguments = std::env::args().skip(1).collect::<Vec<_>>();
    let (run, windows, hero_terms) = match arguments.as_slice() {
        [run, windows] => (run, windows, false),
        [run, windows, option] if option == "hero-terms" => (run, windows, true),
        _ => return Err(Error::new(USAGE)),
    };
    let windows = windows.parse::<usize>().map_err(|_| Error::new(USAGE))?;
    let paths = RunPaths::open(Path::new(run))?;
    let resources = ExtractionResources {
        memory_limit_mb: 12_000,
        threads: 8,
    };
    println!("window\tmatches\ttarget\tphase_s\tcoefficient\tstandard_error\tobservations");
    for window in measure_counter_windows(&paths, resources, windows, hero_terms)? {
        for evidence in &window.evidence {
            for phase in &evidence.phases {
                println!(
                    "{}\t{}\t{}\t{}\t{:.4}\t{:.4}\t{}",
                    window.window,
                    window.matches,
                    evidence.target.label(),
                    phase.phase_s,
                    phase.coefficient,
                    phase.standard_error,
                    phase.observations
                );
            }
        }
    }
    Ok(())
}
