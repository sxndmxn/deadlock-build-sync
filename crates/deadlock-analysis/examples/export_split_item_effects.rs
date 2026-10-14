#![forbid(unsafe_code)]

//! Writes item effects from two disjoint halves of the development matches.
//!
//! Usage: `cargo run --release --example export_split_item_effects -- RUN_DIRECTORY`
//!
//! The output is tab-separated text with one line for each sample, hero, phase, and item.
//! Compare the samples to measure how reliable the effect estimates are.

use std::io::{BufWriter, Write};
use std::path::Path;

use deadlock_analysis::{ExtractionResources, RunPaths, estimate_split_item_effects};
use deadlock_data::{Error, Result};

fn main() -> Result<()> {
    let run = std::env::args()
        .nth(1)
        .ok_or_else(|| Error::new("Usage: export_split_item_effects RUN_DIRECTORY"))?;
    let paths = RunPaths::open(Path::new(&run))?;
    let resources = ExtractionResources {
        memory_limit_mb: 12_000,
        threads: 8,
    };
    let rows = estimate_split_item_effects(&paths, resources)?;
    let mut output = BufWriter::new(std::io::stdout().lock());
    writeln!(
        output,
        "sample\thero_id\tphase_s\titem_id\titem_name\ttier\tadoption\towner_win_rate\teffect\tobservations"
    )?;
    for row in rows {
        writeln!(
            output,
            "{}\t{}\t{}\t{}\t{}\t{}\t{:.6}\t{:.6}\t{:.6}\t{}",
            row.sample,
            row.hero_id,
            row.phase_s,
            row.item_id,
            row.item_name,
            row.tier,
            row.adoption,
            row.owner_win_rate,
            row.effect,
            row.observations
        )?;
    }
    output.flush()?;
    Ok(())
}
