#![forbid(unsafe_code)]

//! Tests whether variant agreement predicts the match result beyond main build agreement.
//!
//! Usage: `cargo run --release --example compare_variant_agreement -- RUN_DIRECTORY [DISTINCT_ITEMS SEPARATION]`
//!
//! The optional values set the variant selection rule. The defaults are the installed rule.
//! The output is tab-separated text with one line for each agreement coefficient.

use std::path::Path;

use deadlock_analysis::{
    ExtractionResources, RunPaths, VariantSelection, compare_variant_agreement,
};
use deadlock_data::{Error, Result};

const USAGE: &str = "Usage: compare_variant_agreement RUN_DIRECTORY [DISTINCT_ITEMS SEPARATION]";

fn main() -> Result<()> {
    let arguments = std::env::args().skip(1).collect::<Vec<_>>();
    let (run, selection) = match arguments.as_slice() {
        [run] => (run, VariantSelection::default()),
        [run, items, separation] => (
            run,
            VariantSelection {
                minimum_distinct_items: items.parse().map_err(|_| Error::new(USAGE))?,
                minimum_separation: separation.parse().map_err(|_| Error::new(USAGE))?,
                ..VariantSelection::default()
            },
        ),
        _ => return Err(Error::new(USAGE)),
    };
    let paths = RunPaths::open(Path::new(run))?;
    let resources = ExtractionResources::default();
    let result = compare_variant_agreement(&paths, resources, selection)?;
    println!("agreement\tcoefficient\tstandard_error\tz\theroes\tobservations");
    for (name, value) in [("main", result.base), ("variant", result.alternative)] {
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
