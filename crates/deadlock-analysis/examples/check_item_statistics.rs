#![forbid(unsafe_code)]

#[expect(
    dead_code,
    reason = "The executable uses only database operations for item statistics."
)]
#[path = "../src/database.rs"]
mod database;
#[path = "../src/item_statistics.rs"]
mod item_statistics;
#[expect(
    dead_code,
    reason = "The executable uses only the database resource limits."
)]
#[path = "../src/refresh_configuration.rs"]
mod refresh_configuration;
#[path = "../src/sql_resources.rs"]
mod sql_resources;

use deadlock_data::{Error, Result};
use deadlock_guides::{
    HERO_BUILD_METHOD, HERO_BUILD_SCHEMA_VERSION, HeroBuildCatalog, ItemStatistics,
    build_hero_presentation,
};
use duckdb::types::Value as SqlValue;

use database::{AnalysisDatabase, Parameters};
use item_statistics::{attach_item_statistics, load_item_statistics};
use refresh_configuration::ExtractionResources;

fn main() -> Result<()> {
    let database = AnalysisDatabase::open(
        std::path::Path::new(":memory:"),
        ExtractionResources {
            memory_limit_mb: 64,
            threads: 1,
        },
    )?;
    seed_purchases(&database)?;
    let statistics = load_item_statistics(
        &database,
        &Parameters::from([
            ("minimum_badge".into(), SqlValue::UInt(61)),
            ("maximum_badge".into(), SqlValue::UInt(115)),
        ]),
    )?;
    let expected = ItemStatistics {
        hero_matches: 4,
        buyer_matches: 2,
        buyer_wins: 1,
    };
    if statistics.get(&(1, 10)) != Some(&expected)
        || statistics.get(&(2, 10))
            != Some(&ItemStatistics {
                hero_matches: 1,
                buyer_matches: 1,
                buyer_wins: 0,
            })
        || statistics.len() != 4
    {
        return Err(Error::new(
            "Item rates mixed heroes, repeated purchases, ranks, or calibration matches",
        ));
    }
    let mut catalog: HeroBuildCatalog =
        serde_json::from_str(include_str!("../../../tests/fixtures/imbue-catalog.json"))?;
    check_legacy_rates(&catalog)?;
    catalog.schema_version = HERO_BUILD_SCHEMA_VERSION;
    catalog.method = HERO_BUILD_METHOD.into();
    if catalog.validate().is_ok() {
        return Err(Error::new(
            "Current catalog accepted missing item purchase counts",
        ));
    }
    let mut variant = catalog.heroes[0].clone();
    variant.variant_id = Some("item-10".into());
    variant.observations = 2;
    variant.core[0].win_rate = 0.99;
    variant.core[0].adoption = 0.99;
    catalog.heroes.push(variant);
    for build in &mut catalog.heroes {
        attach_item_statistics(build, &statistics)?;
    }
    catalog.validate()?;
    check_presentations(&catalog)?;
    check_invalid_counts(&catalog)?;
    let mut missing = statistics;
    missing.remove(&(1, 10));
    if attach_item_statistics(&mut catalog.heroes[0], &missing).is_ok() {
        return Err(Error::new(
            "Item statistics silently accepted missing purchase data",
        ));
    }
    println!("Isolated item purchase statistics checks passed.");
    Ok(())
}

fn seed_purchases(database: &AnalysisDatabase) -> Result<()> {
    database.execute(
        "CREATE TABLE player_matches AS
         SELECT match_id, player_slot, hero_id, average_badge, calibration, won
         FROM (VALUES
             (1, 0, 1, 61, false, true), (2, 0, 1, 115, false, false),
             (3, 0, 1, 80, false, true), (4, 0, 1, 80, false, false),
             (1, 1, 2, 80, false, false), (5, 0, 1, 60, false, true),
             (6, 0, 1, 116, false, true), (7, 0, 1, 80, true, true)
         ) AS p(match_id, player_slot, hero_id, average_badge, calibration, won)",
        &Parameters::new(),
    )?;
    database.execute(
        "CREATE TABLE purchases AS
         SELECT p.match_id, p.player_slot, p.hero_id, p.average_badge,
             p.calibration, p.won, b.item_id, b.item_purchase_ordinal
         FROM player_matches AS p
         INNER JOIN (VALUES
             (1, 0, 10, 1), (1, 0, 10, 2), (2, 0, 10, 1),
             (2, 0, 16, 1), (3, 0, 17, 1), (1, 1, 10, 1),
             (5, 0, 10, 1), (6, 0, 10, 1), (7, 0, 10, 1)
         ) AS b(match_id, player_slot, item_id, item_purchase_ordinal)
         ON p.match_id = b.match_id AND p.player_slot = b.player_slot",
        &Parameters::new(),
    )
}

fn check_legacy_rates(catalog: &HeroBuildCatalog) -> Result<()> {
    catalog.validate()?;
    let mut legacy = catalog.clone();
    legacy.schema_version = 6;
    legacy.method = "item-effect-variants-v1".into();
    legacy.heroes[0].variant_id = Some("item-10".into());
    legacy.validate()?;
    for build in [&catalog.heroes[0], &legacy.heroes[0]] {
        if build.core[0].describe_rates()? != ["unavailable", "unavailable"] {
            return Err(Error::new(
                "Legacy phase rates appeared as complete hero purchase rates",
            ));
        }
    }
    Ok(())
}

fn check_presentations(catalog: &HeroBuildCatalog) -> Result<()> {
    let mut annotations = Vec::new();
    for build in &catalog.heroes {
        let rates = build.core[0].describe_rates()?;
        if rates != ["50.0% (1/2)", "50.0% (2/4)"] {
            return Err(Error::new(
                "Item display used phase rates or lost purchase counts",
            ));
        }
        let presentation = build_hero_presentation(build, catalog, "reference", "Reference")?;
        let items = presentation
            .content()
            .categories
            .iter()
            .flat_map(|category| &category.items)
            .map(|item| item.annotation.clone())
            .collect::<Vec<_>>();
        if !items[0].contains("ITEM WIN RATE: 50.0% (1/2)\nPICK RATE: 50.0% (2/4)") {
            return Err(Error::new(
                "Steam annotations omitted purchase counts or used phase rates",
            ));
        }
        annotations.push(items);
    }
    if annotations[0] != annotations[1] {
        return Err(Error::new(
            "Variant selection changed the item purchase rates",
        ));
    }
    Ok(())
}

fn check_invalid_counts(catalog: &HeroBuildCatalog) -> Result<()> {
    for (hero_matches, buyer_matches, buyer_wins) in [
        (4, 0, 0),
        (4, 2, 3),
        (4, 5, 1),
        (5, 2, 1),
        (4, 2, 2),
        (catalog.cohort.player_matches + 1, 2, 1),
    ] {
        let mut invalid = catalog.clone();
        invalid.heroes[1].core[0].statistics = Some(ItemStatistics {
            hero_matches,
            buyer_matches,
            buyer_wins,
        });
        if invalid.validate().is_ok() {
            return Err(Error::new(
                "Catalog accepted invalid or inconsistent item purchase counts",
            ));
        }
    }
    Ok(())
}
