#![forbid(unsafe_code)]

//! Compares item score rules on the held-out test fold of one extracted run.
//!
//! Usage: `cargo run --release --example compare_item_scoring -- RUN_DIRECTORY [SCALE[:FLOOR] ...]`
//!
//! The output is tab-separated text with one line for each effect scale.
//! The effect scale `inf` selects items by adoption only.

use std::path::Path;

use deadlock_analysis::{
    DEFAULT_SCORING, ExtractionResources, ItemScoring, RunPaths, compare_item_scoring,
};
use deadlock_data::{Error, Result};

const DEFAULT_EFFECT_SCALES: [f64; 6] = [f64::INFINITY, 0.4, 0.2, 0.1, 0.05, 0.025];

fn main() -> Result<()> {
    let mut arguments = std::env::args().skip(1);
    let run = arguments.next().ok_or_else(|| {
        Error::new("Usage: compare_item_scoring RUN_DIRECTORY [SCALE[:FLOOR] ...]")
    })?;
    let paths = RunPaths::open(Path::new(&run))?;
    let mut rules = arguments
        .map(|value| value.parse::<ItemScoring>())
        .collect::<Result<Vec<_>>>()?;
    if rules.is_empty() {
        rules = DEFAULT_EFFECT_SCALES
            .iter()
            .map(|effect_scale| ItemScoring {
                effect_scale: *effect_scale,
                adoption_floor: 0.0,
            })
            .collect();
    }
    let resources = ExtractionResources {
        memory_limit_mb: 12_000,
        threads: 8,
    };
    println!(
        "rule\tdefault\tagreement_coefficient\tstandard_error\tobservations\theroes\tstrong\tmoderate\tlimited\tmedian_core_adoption\trare_core_share"
    );
    for result in compare_item_scoring(&paths, resources, &rules)? {
        let scale = result.scoring.effect_scale;
        let floor = result.scoring.adoption_floor;
        println!(
            "{scale}:{floor}\t{}\t{:.4}\t{:.4}\t{}\t{}\t{}\t{}\t{}\t{:.3}\t{:.3}",
            if scale.total_cmp(&DEFAULT_SCORING.effect_scale).is_eq()
                && floor.total_cmp(&DEFAULT_SCORING.adoption_floor).is_eq()
            {
                "yes"
            } else {
                "no"
            },
            result.pooled.agreement_coefficient,
            result.pooled.standard_error,
            result.pooled.observations,
            result.heroes,
            result.strong,
            result.moderate,
            result.limited,
            result.median_core_adoption,
            result.rare_core_share,
        );
    }
    Ok(())
}
