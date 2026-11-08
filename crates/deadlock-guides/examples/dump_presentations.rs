#![forbid(unsafe_code)]

//! Prints the Steam presentation of every build in a catalog, with a fixed snapshot and persona.
//!
//! Usage: `cargo run --example dump_presentations -- CATALOG_FILE`
//!
//! Two catalogs with the same output install the same Steam builds, apart from the snapshot line.

use std::path::Path;

use deadlock_data::{Error, Result};
use deadlock_guides::{HeroBuildCatalog, build_hero_presentation};

fn main() -> Result<()> {
    let catalog_path = std::env::args()
        .nth(1)
        .ok_or_else(|| Error::new("Usage: dump_presentations CATALOG_FILE"))?;
    let catalog = HeroBuildCatalog::read(Path::new(&catalog_path))?;
    for build in &catalog.heroes {
        let presentation = build_hero_presentation(build, &catalog, "snapshot", "Player")?;
        println!("{:#?}", presentation.content());
    }
    Ok(())
}
