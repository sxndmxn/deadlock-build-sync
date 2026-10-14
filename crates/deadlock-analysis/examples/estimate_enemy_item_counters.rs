#![forbid(unsafe_code)]

//! Tests whether item groups win more when the enemy team owns more of a set of items.
//!
//! Usage: `cargo run --release --example estimate_enemy_item_counters -- RUN_DIRECTORY CONDITION_CLASSES GROUP_CLASSES...`
//!
//! Each class list is comma-separated item class names. The condition is the summed cost of
//! condition items that the enemy team owns at the landmark, standardized within the phase.
//! The output is tab-separated text with one line for each phase and group.

use std::path::Path;

use deadlock_analysis::{ExtractionResources, RunPaths, estimate_enemy_item_counters};
use deadlock_data::{Error, Result};

const USAGE: &str =
    "Usage: estimate_enemy_item_counters RUN_DIRECTORY CONDITION_CLASSES GROUP_CLASSES...";

fn main() -> Result<()> {
    let arguments = std::env::args().skip(1).collect::<Vec<_>>();
    let [run, condition, groups @ ..] = arguments.as_slice() else {
        return Err(Error::new(USAGE));
    };
    if groups.is_empty() {
        return Err(Error::new(USAGE));
    }
    let paths = RunPaths::open(Path::new(run))?;
    let resources = ExtractionResources {
        memory_limit_mb: 12_000,
        threads: 8,
    };
    let condition = condition.split(',').collect::<Vec<_>>();
    let groups = groups
        .iter()
        .map(|group| group.split(',').collect::<Vec<_>>())
        .collect::<Vec<_>>();
    println!("phase_s\tgroup\tcoefficient\tstandard_error\tz\tobservations");
    for result in estimate_enemy_item_counters(&paths, resources, &condition, &groups)? {
        for (group, interaction) in result.interactions.iter().enumerate() {
            println!(
                "{}\t{group}\t{:.4}\t{:.4}\t{:.1}\t{}",
                result.phase_s,
                interaction.coefficient,
                interaction.standard_error,
                interaction.coefficient / interaction.standard_error,
                result.observations
            );
        }
    }
    Ok(())
}
