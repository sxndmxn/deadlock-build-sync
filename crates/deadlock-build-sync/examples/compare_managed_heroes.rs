//! Temporary: compares each installed managed build with the generated presentation of its hero.
use std::collections::BTreeMap;
use std::path::Path;

use deadlock_data::{Error, Result};
use deadlock_guides::{HeroBuildCatalog, build_hero_presentation};
use deadlock_steam::{BuildKey, compare_managed_builds, parse_hero_build_metadata, read_cache};

fn main() -> Result<()> {
    let mut arguments = std::env::args().skip(1);
    let (Some(catalog_path), Some(cache_path), Some(account)) =
        (arguments.next(), arguments.next(), arguments.next())
    else {
        return Err(Error::new(
            "usage: compare_managed_heroes CATALOG CACHE ACCOUNT_ID",
        ));
    };
    let account_id: u32 = account
        .parse()
        .map_err(|error| Error::new(format!("{error}")))?;
    let catalog = HeroBuildCatalog::read(Path::new(&catalog_path))?;
    let cache = read_cache(Path::new(&cache_path))?;
    let snapshot = cache
        .document()
        .root
        .field("Unpublished")?
        .array()?
        .iter()
        .filter_map(|value| value.blob().ok())
        .filter_map(|bytes| parse_hero_build_metadata(bytes).ok()?.description)
        .find_map(|text| {
            text.lines().find_map(|line| {
                line.strip_prefix("Snapshot: ")?
                    .strip_suffix('.')
                    .map(str::to_owned)
            })
        })
        .ok_or_else(|| Error::new("No installed build states a snapshot"))?;
    for build in &catalog.heroes {
        let key = BuildKey {
            hero_id: build.hero_id,
            path_id: build.path_id(),
        };
        let presentation = build_hero_presentation(build, &catalog, &snapshot, "Build Preview")?;
        let expected = BTreeMap::from([(key, presentation)]);
        let comparison = compare_managed_builds(&cache, account_id, &expected)?;
        println!(
            "{:>3} {:<16} {}",
            build.hero_id,
            build.hero_name,
            if comparison.is_current {
                "match"
            } else {
                "differ"
            }
        );
    }
    Ok(())
}
