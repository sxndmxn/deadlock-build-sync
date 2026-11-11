#![forbid(unsafe_code)]

//! Lists the managed builds in a Steam hero build cache file or a backup of it.
//!
//! Usage: `cargo run --example list_managed_builds -- CACHE_FILE ACCOUNT_ID`
//!
//! The output is tab-separated text with one line for each managed build.
//! A build with the legacy marker has no build path and shows `legacy`.

use std::path::Path;

use deadlock_data::{Error, Result};
use deadlock_steam::{ManagedScan, parse_hero_build_metadata, read_cache};

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
    let values = cache.document().root.field("Unpublished")?.array()?;
    let scan = ManagedScan::scan(&cache, account_id)?;
    println!("hero_id\tpath\tname");
    for (index, entry) in scan.managed() {
        let name = parse_hero_build_metadata(values[index].blob()?)?
            .name
            .unwrap_or_default();
        println!(
            "{}\t{}\t{name}",
            entry.hero_id,
            entry
                .trailer
                .as_ref()
                .map_or("legacy", |trailer| trailer.path_id.as_str())
        );
    }
    if scan.unreadable() > 0 {
        eprintln!("{} private builds cannot be parsed", scan.unreadable());
    }
    Ok(())
}
