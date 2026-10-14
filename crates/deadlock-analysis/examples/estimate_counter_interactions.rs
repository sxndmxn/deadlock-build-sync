#![forbid(unsafe_code)]

//! Tests whether defensive items win more against the matching enemy damage type.
//!
//! Usage: `cargo run --release --example estimate_counter_interactions -- RUN_DIRECTORY [SPIRIT_ITEMS WEAPON_ITEMS]`
//!
//! `SPIRIT_ITEMS` and `WEAPON_ITEMS` are comma-separated item names that replace the default groups.
//!
//! The output is tab-separated text with one line for each phase.
//! A positive spirit defense coefficient and a negative weapon defense coefficient
//! agree with the hypothesis.

use std::path::Path;

use deadlock_analysis::{ExtractionResources, RunPaths, estimate_counter_interactions};
use deadlock_data::{Error, Result};

const SPIRIT_DEFENSE: [&str; 6] = [
    "Spirit Shielding",
    "Enchanter's Emblem",
    "Spirit Resilience",
    "Counterspell",
    "Witchmail",
    "Dispel Magic",
];
const WEAPON_DEFENSE: [&str; 6] = [
    "Weapon Shielding",
    "Battle Vest",
    "Bullet Resilience",
    "Metal Skin",
    "Plated Armor",
    "Return Fire",
];

const USAGE: &str =
    "Usage: estimate_counter_interactions RUN_DIRECTORY [SPIRIT_ITEMS WEAPON_ITEMS]";

fn main() -> Result<()> {
    let arguments = std::env::args().skip(1).collect::<Vec<_>>();
    let (run, spirit_defense, weapon_defense) = match arguments.as_slice() {
        [run] => (run, SPIRIT_DEFENSE.to_vec(), WEAPON_DEFENSE.to_vec()),
        [run, spirit, weapon] => (
            run,
            spirit.split(',').collect(),
            weapon.split(',').collect(),
        ),
        _ => return Err(Error::new(USAGE)),
    };
    let paths = RunPaths::open(Path::new(run))?;
    let resources = ExtractionResources {
        memory_limit_mb: 12_000,
        threads: 8,
    };
    println!(
        "phase_s\tspirit_defense\tstandard_error\tweapon_defense\tstandard_error\tobservations"
    );
    for result in
        estimate_counter_interactions(&paths, resources, &spirit_defense, &weapon_defense)?
    {
        println!(
            "{}\t{:.4}\t{:.4}\t{:.4}\t{:.4}\t{}",
            result.phase_s,
            result.spirit_defense,
            result.spirit_defense_standard_error,
            result.weapon_defense,
            result.weapon_defense_standard_error,
            result.observations
        );
    }
    Ok(())
}
