#![forbid(unsafe_code)]

//! Compares item score rules on the held-out test fold of one extracted run.
//!
//! Usage: `cargo run --release --example compare_item_scoring -- RUN_DIRECTORY [EFFECT_SCALE ...]`
//!
//! The output is tab-separated text with one line for each effect scale.
//! The effect scale `inf` selects items by adoption only.

use std::path::PathBuf;

use deadlock_analysis::{
    DEFAULT_SCORING, ExtractionResources, ItemScoring, RunPaths, compare_item_scoring,
};
use deadlock_data::{Error, Result};

const DEFAULT_EFFECT_SCALES: [f64; 6] = [f64::INFINITY, 0.4, 0.2, 0.1, 0.05, 0.025];

fn main() -> Result<()> {
    let mut arguments = std::env::args().skip(1);
    let run = PathBuf::from(arguments.next().ok_or_else(|| {
        Error::new("Usage: compare_item_scoring RUN_DIRECTORY [EFFECT_SCALE ...]")
    })?);
    if !run.join("manifest.json").is_file() {
        return Err(Error::new(format!(
            "Run directory has no manifest.json: {}",
            run.display()
        )));
    }
    let mut scales = arguments
        .map(|value| {
            value
                .parse::<f64>()
                .ok()
                .filter(|scale| *scale > 0.0)
                .ok_or_else(|| Error::new(format!("Effect scale must be positive: {value}")))
        })
        .collect::<Result<Vec<_>>>()?;
    if scales.is_empty() {
        scales = DEFAULT_EFFECT_SCALES.to_vec();
    }
    let paths = RunPaths {
        raw: run.join("raw"),
        data: run.join("data"),
        tables: run.join("tables"),
        run,
    };
    let rules = scales
        .into_iter()
        .map(|effect_scale| ItemScoring { effect_scale })
        .collect::<Vec<_>>();
    let resources = ExtractionResources {
        memory_limit_mb: 12_000,
        threads: 8,
    };
    println!(
        "effect_scale\tdefault\tagreement_coefficient\tstandard_error\tobservations\theroes\tstrong\tmoderate\tlimited"
    );
    for result in compare_item_scoring(&paths, resources, &rules)? {
        let scale = result.scoring.effect_scale;
        println!(
            "{scale}\t{}\t{:.4}\t{:.4}\t{}\t{}\t{}\t{}\t{}",
            if scale.total_cmp(&DEFAULT_SCORING.effect_scale).is_eq() {
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
        );
    }
    Ok(())
}
