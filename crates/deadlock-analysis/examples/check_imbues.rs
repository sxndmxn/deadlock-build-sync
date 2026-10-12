#![forbid(unsafe_code)]

#[expect(
    dead_code,
    reason = "The executable uses only the imbue database operations."
)]
#[path = "../src/database.rs"]
mod database;
#[path = "../src/item_imbues.rs"]
mod item_imbues;
#[expect(
    dead_code,
    reason = "The executable uses only the database resource limits."
)]
#[path = "../src/refresh_configuration.rs"]
mod refresh_configuration;
#[path = "../src/sql_resources.rs"]
mod sql_resources;

use deadlock_data::{Error, Result};
use deadlock_guides::{HeroBuild, HeroBuildCatalog, ImbueTarget};
use duckdb::types::Value as SqlValue;
use serde_json::{Value, json};

use database::{AnalysisDatabase, Parameters};
use item_imbues::{ItemImbues, attach_item_imbues, load_item_imbues};
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
    let targets = load_item_imbues(
        &database,
        &Parameters::from([
            ("minimum_badge".into(), SqlValue::UInt(61)),
            ("maximum_badge".into(), SqlValue::UInt(115)),
        ]),
    )?;
    let catalog: HeroBuildCatalog =
        serde_json::from_str(include_str!("../../../tests/fixtures/imbue-catalog.json"))?;
    let build = catalog
        .heroes
        .first()
        .ok_or_else(|| Error::new("Imbue fixture has no hero"))?;
    let assets = reference_assets();
    let mut selected = build.clone();
    for item in selected.core.iter_mut().chain(&mut selected.situational) {
        item.imbue_target = None;
    }
    attach_item_imbues(&mut selected, &targets, &assets);
    if selected != *build || targets.get(&(2, 10)).map(|target| target.ability_id) != Some(201) {
        return Err(Error::new(
            "Imbue selection mixed heroes, items, or purchase filters",
        ));
    }
    check_rejected_targets(build, &targets, &assets)?;
    check_asset_restrictions(build, &targets, &assets)?;
    println!("Isolated imbue selection checks passed.");
    Ok(())
}

fn seed_purchases(database: &AnalysisDatabase) -> Result<()> {
    database.execute(
        "CREATE TABLE purchases (hero_id UBIGINT, item_id UBIGINT, imbued_ability_id UBIGINT,
         average_badge UINTEGER, calibration BOOLEAN, item_purchase_ordinal UBIGINT)",
        &Parameters::new(),
    )?;
    for (hero, item, ability, count, badge, calibration, ordinal) in [
        (1_u64, 10_u64, 101_u64, 30, 61_u32, false, 1_u64),
        (1, 10, 102, 10, 115, false, 1),
        (1, 10, 102, 100, 60, false, 1),
        (1, 10, 102, 100, 116, false, 1),
        (1, 10, 102, 100, 80, true, 1),
        (1, 10, 102, 100, 80, false, 2),
        (1, 10, 0, 100, 80, false, 1),
        (1, 16, 101, 30, 80, false, 1),
        (1, 17, 102, 20, 80, false, 1),
        (1, 17, 101, 10, 80, false, 1),
        (2, 10, 201, 25, 80, false, 1),
    ] {
        let row = vec![
            SqlValue::UBigInt(hero),
            SqlValue::UBigInt(item),
            SqlValue::UBigInt(ability),
            SqlValue::UInt(badge),
            SqlValue::Boolean(calibration),
            SqlValue::UBigInt(ordinal),
        ];
        database.insert_rows(
            "INSERT INTO purchases VALUES (?, ?, ?, ?, ?, ?)",
            &std::iter::repeat_n(row, count).collect::<Vec<_>>(),
        )?;
    }
    Ok(())
}

fn reference_assets() -> Vec<Value> {
    vec![
        json!({"id":10,"type":"upgrade","imbue":"imbue_active"}),
        json!({"id":16,"type":"upgrade"}),
        json!({"id":17,"type":"upgrade","imbue":"imbue_active_non_ult"}),
        json!({"id":101,"type":"ability","ability_type":"signature","hero":1}),
        json!({"id":102,"type":"ability","ability_type":"signature","heroes":[1]}),
        json!({"id":104,"type":"ability","ability_type":"ultimate","hero":1}),
    ]
}

fn check_rejected_targets(build: &HeroBuild, targets: &ItemImbues, assets: &[Value]) -> Result<()> {
    for (ability_id, matches, observations) in [
        (101, 19, 19),
        (101, 20, 40),
        (101, 21, 20),
        (0, 30, 40),
        (999, 30, 40),
    ] {
        let mut targets = targets.clone();
        targets.insert(
            (1, 10),
            ImbueTarget {
                ability_id,
                matches,
                observations,
            },
        );
        let mut selected = build.clone();
        attach_item_imbues(&mut selected, &targets, assets);
        require_unset(&selected, 10)?;
    }
    let mut selected = build.clone();
    selected.ability_ids.clear();
    attach_item_imbues(&mut selected, targets, assets);
    require_unset(&selected, 10)
}

fn check_asset_restrictions(
    build: &HeroBuild,
    targets: &ItemImbues,
    assets: &[Value],
) -> Result<()> {
    for (asset_id, field, value) in [
        (101, "hero", json!(2)),
        (101, "type", json!("upgrade")),
        (10, "imbue", json!("unknown")),
        (101, "id", json!(999)),
    ] {
        let mut assets = assets.to_vec();
        let asset = assets
            .iter_mut()
            .find(|asset| asset["id"] == asset_id)
            .ok_or_else(|| Error::new("Reference asset is missing"))?;
        asset[field] = value;
        let mut selected = build.clone();
        attach_item_imbues(&mut selected, targets, &assets);
        require_unset(&selected, 10)?;
    }
    let mut targets = targets.clone();
    targets.insert(
        (1, 17),
        ImbueTarget {
            ability_id: 104,
            matches: 30,
            observations: 40,
        },
    );
    let mut selected = build.clone();
    attach_item_imbues(&mut selected, &targets, assets);
    require_unset(&selected, 17)
}

fn require_unset(build: &HeroBuild, item_id: u64) -> Result<()> {
    let item = build
        .core
        .iter()
        .chain(&build.situational)
        .find(|item| item.item_id == item_id)
        .ok_or_else(|| Error::new("Reference item is missing"))?;
    if item.imbue_target.is_some() {
        return Err(Error::new("Imbue selection accepted an unsupported target"));
    }
    Ok(())
}
