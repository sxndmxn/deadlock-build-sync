use std::fs;

use deadlock_build_sync::write_build_artifacts;
use deadlock_data::{Error, Result};
use deadlock_guides::{
    BuildPresentation, CounterEvidence, CounterPanel, CounterPhase, DamageType, HERO_BUILD_METHOD,
    HERO_BUILD_SCHEMA_VERSION, HeroBuildCatalog, ItemStatistics, MAXIMUM_COUNTER_ITEMS,
    build_hero_presentation,
};
use deadlock_steam::encode_hero_build;

pub fn check_counter_panels() -> Result<()> {
    let catalog = create_counter_catalog()?;
    check_counter_presentation(&catalog)?;
    check_counter_export(&catalog)?;
    check_invalid_counters(&catalog)
}

fn create_counter_catalog() -> Result<HeroBuildCatalog> {
    let mut catalog: HeroBuildCatalog = serde_json::from_str(include_str!(
        "../../../../tests/fixtures/imbue-catalog.json"
    ))?;
    catalog.schema_version = HERO_BUILD_SCHEMA_VERSION;
    catalog.method = HERO_BUILD_METHOD.into();
    let build = &mut catalog.heroes[0];
    for item in build.core.iter_mut().chain(&mut build.situational) {
        item.statistics = Some(ItemStatistics {
            hero_matches: 100,
            buyer_matches: 40,
            buyer_wins: 21,
        });
    }
    build.counters = vec![CounterPanel {
        damage_type: DamageType::Weapon,
        items: vec![build.situational[0].clone()],
    }];
    catalog.counter_evidence = vec![CounterEvidence {
        damage_type: DamageType::Weapon,
        phases: vec![
            CounterPhase {
                phase_s: 1200,
                coefficient: 0.036,
                standard_error: 0.008,
                observations: 1000,
            },
            CounterPhase {
                phase_s: 1800,
                coefficient: 0.052,
                standard_error: 0.009,
                observations: 800,
            },
        ],
    }];
    catalog.validate()?;
    Ok(catalog)
}

fn check_counter_presentation(catalog: &HeroBuildCatalog) -> Result<()> {
    let presentation =
        build_hero_presentation(&catalog.heroes[0], catalog, "snapshot", "Reference")?;
    let content = presentation.content();
    let names = content
        .categories
        .iter()
        .map(|category| category.name.as_str())
        .collect::<Vec<_>>();
    if names
        != [
            "MAIN CORE",
            "VS WEAPON",
            "TIER 1",
            "TIER 2",
            "TIER 3",
            "TIER 4",
        ]
        || !content.categories[1].description.contains("z ≥ 4.5")
        || !content.description.contains("VS panels")
    {
        return Err(Error::new(
            "Presentation omitted the counter panel or its evidence",
        ));
    }
    encode_hero_build(&presentation, 1, 7, 1)?;
    let mut reversed = content.clone();
    let mut spirit = reversed.categories[1].clone();
    spirit.name = "VS SPIRIT".into();
    reversed.categories.insert(1, spirit);
    if BuildPresentation::new(reversed).is_ok() {
        return Err(Error::new(
            "Presentation accepted VS SPIRIT before VS WEAPON",
        ));
    }
    Ok(())
}

fn check_counter_export(catalog: &HeroBuildCatalog) -> Result<()> {
    let root = tempfile::tempdir()?;
    let directory = root.path().join("artifacts");
    write_build_artifacts(&directory, catalog)?;
    let markdown = fs::read_to_string(directory.join("builds/reference-hero.md"))?;
    if !markdown.contains("## VS WEAPON") || !markdown.contains("Counter test at 30 min: +0.052") {
        return Err(Error::new(
            "Markdown export omitted the counter panel or its evidence",
        ));
    }
    Ok(())
}

fn check_invalid_counters(catalog: &HeroBuildCatalog) -> Result<()> {
    let mut no_evidence = catalog.clone();
    no_evidence.counter_evidence.clear();
    let mut negative = catalog.clone();
    negative.counter_evidence[0].phases[0].coefficient = -0.01;
    let mut core_item = catalog.clone();
    core_item.heroes[0].counters[0].items[0] = core_item.heroes[0].core[0].clone();
    let mut too_many = catalog.clone();
    let item = too_many.heroes[0].counters[0].items[0].clone();
    too_many.heroes[0].counters[0].items = (0..=MAXIMUM_COUNTER_ITEMS)
        .map(|index| {
            let mut copy = item.clone();
            copy.item_id = 1000 + u64::try_from(index).unwrap_or_default();
            copy
        })
        .collect();
    for (invalid, reason) in [
        (no_evidence, "a counter panel without run evidence"),
        (negative, "counter evidence with a negative coefficient"),
        (core_item, "a counter panel item in CORE"),
        (too_many, "a counter panel with too many items"),
    ] {
        if invalid.validate().is_ok() {
            return Err(Error::new(format!("Catalog accepted {reason}")));
        }
    }
    Ok(())
}
