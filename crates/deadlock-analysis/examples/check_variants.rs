#![forbid(unsafe_code)]

#[path = "../src/build_assembly.rs"]
mod build_assembly;
#[path = "../src/build_variants.rs"]
mod build_variants;
#[expect(
    dead_code,
    reason = "The reference check supplies item effects without fitting a model."
)]
#[path = "../src/item_effects.rs"]
mod item_effects;
#[expect(
    dead_code,
    reason = "The reference check supplies item effects without fitting a model."
)]
#[path = "../src/ridge_logistic.rs"]
mod ridge_logistic;

use deadlock_data::{Error, Result};

use build_assembly::{PHASES, PurchaseMedians, assemble_build};
use build_variants::{assemble_item_variant, select_item_variants};
use item_effects::{EffectTable, HeroLandmarkEffects, ItemAsset, ItemCatalog, LandmarkState};

fn main() -> Result<()> {
    let catalog = create_items()?;
    let effects = create_effects(&catalog);
    let medians = PurchaseMedians::new();
    let main = assemble_build(1, &effects, &catalog, &medians)
        .ok_or_else(|| Error::new("Reference main build is missing"))?;
    let states = create_states(120);
    let references = states.iter().collect::<Vec<_>>();
    let variants = select_item_variants(1, &references, &effects, &catalog, &medians, &main)?;
    let keys = variants
        .iter()
        .map(|variant| variant.build.key_item_id)
        .collect::<Vec<_>>();
    if keys != [20, 30] {
        return Err(Error::new(
            "Variant selection lost a strategy or repeated the same strategy",
        ));
    }
    if variants.iter().any(|variant| variant.owners != 120) {
        return Err(Error::new(
            "Variant owner counts include repeated landmarks",
        ));
    }
    let mut reversed = references.clone();
    reversed.reverse();
    let repeated = select_item_variants(1, &reversed, &effects, &catalog, &medians, &main)?;
    if repeated
        .iter()
        .map(|variant| variant.build.key_item_id)
        .collect::<Vec<_>>()
        != keys
    {
        return Err(Error::new("Source row order changed the selected variants"));
    }
    check_variant_cohorts(&references, &effects, &catalog)?;
    let sparse = create_states(60);
    let sparse = sparse.iter().chain(&sparse).collect::<Vec<_>>();
    if assemble_item_variant(1, 20, &sparse, &effects, &catalog, &medians)?.is_some() {
        return Err(Error::new(
            "Repeated landmarks inflated the distinct owner count",
        ));
    }
    let single = references
        .iter()
        .copied()
        .filter(|state| state.match_id < 120)
        .collect::<Vec<_>>();
    if !select_item_variants(1, &single, &effects, &catalog, &medians, &main)?.is_empty() {
        return Err(Error::new(
            "Variant selection forced alternatives for one observed strategy",
        ));
    }
    println!("Isolated strategy selection checks passed.");
    Ok(())
}

fn check_variant_cohorts(
    states: &[&LandmarkState],
    effects: &EffectTable,
    catalog: &ItemCatalog,
) -> Result<()> {
    for key in [20, 30] {
        let variant =
            assemble_item_variant(1, key, states, effects, catalog, &PurchaseMedians::new())?
                .ok_or_else(|| Error::new("Supported reference variant is missing"))?;
        let expensive = variant
            .build
            .core
            .iter()
            .filter(|item| item.tier >= 3)
            .map(|item| item.item_id)
            .collect::<Vec<_>>();
        if expensive != [key, key + 1, key + 2] {
            return Err(Error::new(
                "Variant assembly mixed items from separate strategies",
            ));
        }
        if variant.build.situational.iter().any(|item| {
            variant
                .build
                .core
                .iter()
                .any(|core| core.item_id == item.item_id)
        }) {
            return Err(Error::new("Variant situational items repeat a CORE item"));
        }
        if variant.build.phase_sets[&540]
            .iter()
            .copied()
            .collect::<Vec<_>>()
            != [1, 2, 3]
        {
            return Err(Error::new(
                "Variant assembly lost its owners' early purchases",
            ));
        }
    }
    let mut other_hero = states
        .iter()
        .map(|state| (*state).clone())
        .collect::<Vec<_>>();
    for state in &mut other_hero {
        state.hero_id = 2;
    }
    let references = other_hero.iter().collect::<Vec<_>>();
    if assemble_item_variant(
        1,
        20,
        &references,
        effects,
        catalog,
        &PurchaseMedians::new(),
    )?
    .is_some()
    {
        return Err(Error::new("Variant assembly used another hero's owners"));
    }
    Ok(())
}

fn create_items() -> Result<ItemCatalog> {
    let mut items = Vec::new();
    for id in [1, 2, 3, 10, 11, 12, 20, 21, 22, 30, 31, 32] {
        items.push(ItemAsset {
            item_id: id,
            item_name: format!("Item {id}"),
            class_name: format!("item_{id}"),
            tier: if id < 10 { 1 } else { 3 },
            cost: if id < 10 { 800 } else { 3200 },
            component_items_json: "[]".into(),
        });
    }
    ItemCatalog::new(items)
}

fn create_effects(catalog: &ItemCatalog) -> EffectTable {
    PHASES
        .into_iter()
        .map(|phase| {
            let adoption = catalog
                .items
                .iter()
                .map(|item| {
                    if item.item_id < 10 {
                        1.0
                    } else if phase == 540 {
                        0.0
                    } else if item.item_id < 20 {
                        0.7
                    } else {
                        0.15
                    }
                })
                .collect();
            (
                (1, phase),
                HeroLandmarkEffects {
                    effects: vec![0.1; catalog.items.len()],
                    adoption,
                    owner_win_rates: vec![0.5; catalog.items.len()],
                    median_spend: if phase == 540 { 2400 } else { 12000 },
                    observations: 360,
                },
            )
        })
        .collect()
}

fn create_states(owners: u32) -> Vec<LandmarkState> {
    let mut states = Vec::new();
    for group in 0..3 {
        for owner in 0..owners {
            for landmark_s in PHASES {
                let mut item_ids = vec![1, 2, 3];
                if landmark_s > 540 {
                    item_ids.extend((10 + group * 10)..(13 + group * 10));
                }
                states.push(LandmarkState {
                    match_id: group * u64::from(owners) + u64::from(owner),
                    player_slot: 0,
                    team_id: 0,
                    hero_id: 1,
                    fold: "development".into(),
                    landmark_s,
                    won: owner % 2 == 0,
                    average_badge: 80,
                    net_worth: 15000,
                    team_lead: 0.0,
                    item_ids,
                    enemy_spirit_share: 0.4,
                });
            }
        }
    }
    states
}
