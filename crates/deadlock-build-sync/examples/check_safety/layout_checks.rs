use deadlock_data::{Error, Result, sha256};
use deadlock_guides::{HeroBuildCatalog, build_hero_presentation};

/// Item counts and the sizes that the game command Compact All gave them on 2026-11-01.
const COMPACT_SIZES: [(usize, f32, f32); 9] = [
    (1, 100.0, 162.75),
    (2, 175.5, 162.75),
    (4, 339.0, 162.75),
    (5, 420.75, 162.75),
    (6, 502.5, 162.75),
    (10, 420.75, 282.75),
    (12, 502.5, 282.75),
    (13, 420.75, 402.75),
    (14, 420.75, 402.75),
];

pub fn check_compact_layout() -> Result<()> {
    let catalog: HeroBuildCatalog = serde_json::from_str(include_str!(
        "../../../../tests/fixtures/imbue-catalog.json"
    ))?;
    let reference = catalog
        .heroes
        .first()
        .ok_or_else(|| Error::new("Layout fixture has no hero"))?;
    let key_item = reference
        .core
        .first()
        .ok_or_else(|| Error::new("Layout fixture has no CORE item"))?;
    for (item_count, width, height) in COMPACT_SIZES {
        let mut build = reference.clone();
        build.core = (0..item_count)
            .map(|index| {
                let mut item = key_item.clone();
                item.item_id += u64::try_from(index)? * 1000;
                Ok(item)
            })
            .collect::<Result<_>>()?;
        let presentation =
            build_hero_presentation(&build, &catalog, &sha256(b"layout fixture"), "Reference")?;
        let core = presentation
            .content()
            .categories
            .first()
            .ok_or_else(|| Error::new("Presentation has no MAIN CORE"))?;
        if (core.width, core.height) != (width, height) {
            return Err(Error::new(format!(
                "MAIN CORE with {item_count} items is {}x{}, but Compact All gives {width}x{height}",
                core.width, core.height
            )));
        }
    }
    Ok(())
}
