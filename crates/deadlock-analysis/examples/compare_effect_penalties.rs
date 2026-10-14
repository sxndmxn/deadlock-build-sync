#![forbid(unsafe_code)]

//! Compares ridge penalties by held-out log loss on one extracted run.
//!
//! Usage: `cargo run --release --example compare_effect_penalties -- RUN_DIRECTORY [GLOBAL:HERO ...]`
//!
//! The output is tab-separated text with one line for each penalty pair.
//! A lower log loss means better predictions of match results.

use std::path::Path;

use deadlock_analysis::{
    DEFAULT_PENALTIES, EffectPenalties, ExtractionResources, RunPaths, compare_effect_penalties,
};
use deadlock_data::{Error, Result};

const GLOBAL_PENALTIES: [f64; 5] = [1.0, 5.0, 20.0, 50.0, 200.0];
const HERO_PENALTIES: [f64; 4] = [20.0, 100.0, 300.0, 1000.0];
/// Penalties large enough to remove all item effects. This pair is the baseline.
const BASELINE: EffectPenalties = EffectPenalties {
    global_item: 1e9,
    hero_item: 1e9,
};

fn main() -> Result<()> {
    let mut arguments = std::env::args().skip(1);
    let run = arguments.next().ok_or_else(|| {
        Error::new("Usage: compare_effect_penalties RUN_DIRECTORY [GLOBAL:HERO ...]")
    })?;
    let paths = RunPaths::open(Path::new(&run))?;
    let mut grid = arguments
        .map(|value| parse_penalties(&value))
        .collect::<Result<Vec<_>>>()?;
    if grid.is_empty() {
        grid.push(BASELINE);
        for global_item in GLOBAL_PENALTIES {
            for hero_item in HERO_PENALTIES {
                grid.push(EffectPenalties {
                    global_item,
                    hero_item,
                });
            }
        }
    }
    let resources = ExtractionResources {
        memory_limit_mb: 12_000,
        threads: 8,
    };
    println!(
        "global_item\thero_item\tdefault\tlog_loss\tdifference_from_first\tstandard_error\tobservations"
    );
    for result in compare_effect_penalties(&paths, resources, &grid)? {
        let penalties = result.penalties;
        let default = penalties
            .global_item
            .total_cmp(&DEFAULT_PENALTIES.global_item)
            .is_eq()
            && penalties
                .hero_item
                .total_cmp(&DEFAULT_PENALTIES.hero_item)
                .is_eq();
        println!(
            "{}\t{}\t{}\t{:.6}\t{:.6}\t{:.6}\t{}",
            penalties.global_item,
            penalties.hero_item,
            if default { "yes" } else { "no" },
            result.log_loss,
            result.difference,
            result.difference_standard_error,
            result.observations
        );
    }
    Ok(())
}

fn parse_penalties(value: &str) -> Result<EffectPenalties> {
    let parse = |text: &str| text.parse::<f64>().ok().filter(|penalty| *penalty > 0.0);
    value
        .split_once(':')
        .and_then(|(global, hero)| {
            Some(EffectPenalties {
                global_item: parse(global)?,
                hero_item: parse(hero)?,
            })
        })
        .ok_or_else(|| {
            Error::new(format!(
                "Penalties must be GLOBAL:HERO with positive values: {value}"
            ))
        })
}
