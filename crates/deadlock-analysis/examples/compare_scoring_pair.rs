#![forbid(unsafe_code)]

//! Tests whether builds of one effect scale add held-out signal beyond builds of another scale.
//!
//! Usage: `cargo run --release --example compare_scoring_pair -- RUN_DIRECTORY BASE_SCALE ALTERNATIVE_SCALE`
//!
//! The output is tab-separated text with one line for each agreement coefficient.
//! A positive alternative coefficient means that the alternative builds add signal.

use std::path::Path;

use deadlock_analysis::{ExtractionResources, ItemScoring, RunPaths, compare_scoring_pair};
use deadlock_data::{Error, Result};

const USAGE: &str = "Usage: compare_scoring_pair RUN_DIRECTORY BASE_SCALE ALTERNATIVE_SCALE";

fn main() -> Result<()> {
    let arguments = std::env::args().skip(1).collect::<Vec<_>>();
    let [run, base, alternative] = arguments.as_slice() else {
        return Err(Error::new(USAGE));
    };
    let scale = |text: &str| {
        text.parse::<f64>()
            .ok()
            .filter(|scale| *scale > 0.0)
            .map(|effect_scale| ItemScoring { effect_scale })
            .ok_or_else(|| Error::new(USAGE))
    };
    let paths = RunPaths::open(Path::new(run))?;
    let resources = ExtractionResources {
        memory_limit_mb: 12_000,
        threads: 8,
    };
    let result = compare_scoring_pair(&paths, resources, scale(base)?, scale(alternative)?)?;
    println!("agreement\tcoefficient\tstandard_error\tz\theroes\tobservations");
    for (name, value) in [(base, result.base), (alternative, result.alternative)] {
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
