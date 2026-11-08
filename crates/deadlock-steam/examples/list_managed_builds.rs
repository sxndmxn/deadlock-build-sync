#![forbid(unsafe_code)]

//! Lists the managed builds in a Steam hero build cache file.
//!
//! Usage: `cargo run --example list_managed_builds -- CACHE_FILE ACCOUNT_ID`
//!
//! The output is tab-separated text with one line for each managed build.

use std::path::Path;

use deadlock_data::{Error, Result};
use deadlock_steam::{parse_hero_build_metadata, read_cache};

fn main() -> Result<()> {
    let mut arguments = std::env::args().skip(1);
    let (Some(cache_path), Some(account)) = (arguments.next(), arguments.next()) else {
        return Err(Error::new(
            "Usage: list_managed_builds CACHE_FILE ACCOUNT_ID",
        ));
    };
    let account_id: u32 = account
        .parse()
        .map_err(|error| Error::new(format!("Invalid account ID: {error}")))?;
    let cache = read_cache(Path::new(&cache_path))?;
    println!("hero_id\tpath\tname");
    for value in cache.document().root.field("Unpublished")?.array()? {
        let Ok(bytes) = value.blob() else {
            continue;
        };
        let metadata = parse_hero_build_metadata(bytes)?;
        let Some(hero_id) = metadata.hero_id else {
            continue;
        };
        if !metadata.is_managed(hero_id, account_id) {
            continue;
        }
        println!(
            "{hero_id}\t{}\t{}",
            metadata.managed_path().unwrap_or("main"),
            metadata.name.as_deref().unwrap_or_default()
        );
    }
    Ok(())
}
