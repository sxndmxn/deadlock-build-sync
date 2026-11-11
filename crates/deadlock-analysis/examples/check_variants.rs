#![forbid(unsafe_code)]

#[path = "../src/build_assembly.rs"]
mod build_assembly;
#[expect(
    dead_code,
    reason = "The reference check uses the default rule and does not report gates."
)]
#[path = "../src/build_variants.rs"]
mod build_variants;
#[expect(
    dead_code,
    reason = "The reference check reads the dropped candidates and the key items only."
)]
#[path = "../src/hero_assembly.rs"]
mod hero_assembly;
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

use build_assembly::{PHASES, PurchaseMedians, assemble_build, assemble_fallback_build};
use build_variants::{
    VariantGate, VariantSelection, assemble_item_variant, explain_item_variants,
    select_item_variants_with_rule,
};
use hero_assembly::{AssemblyContext, HeroAssembly};
use item_effects::{
    ALL_HEROES, EffectTable, HeroLandmarkEffects, ItemAsset, ItemCatalog, LandmarkState,
};

fn main() -> Result<()> {
    let catalog = create_items()?;
    let effects = create_effects(&catalog);
    let medians = PurchaseMedians::new();
    check_fallback_build(&effects, &catalog, &medians)?;
    let main = assemble_build(1, &effects, &catalog, &medians)
        .ok_or_else(|| Error::new("Reference main build is missing"))?;
    let states = create_states(120);
    let references = states.iter().collect::<Vec<_>>();
    let variants = select_item_variants_with_rule(
        1,
        &references,
        &effects,
        &catalog,
        &medians,
        &main,
        VariantSelection::default(),
    )?;
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
    let repeated = select_item_variants_with_rule(
        1,
        &reversed,
        &effects,
        &catalog,
        &medians,
        &main,
        VariantSelection::default(),
    )?;
    if repeated
        .iter()
        .map(|variant| variant.build.key_item_id)
        .collect::<Vec<_>>()
        != keys
    {
        return Err(Error::new("Source row order changed the selected variants"));
    }
    check_variant_cohorts(&references, &effects, &catalog)?;
    check_separation_rule(&effects, &catalog, &medians, &main)?;
    check_production_drop(&effects, &catalog, &medians)?;
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
    if !select_item_variants_with_rule(
        1,
        &single,
        &effects,
        &catalog,
        &medians,
        &main,
        VariantSelection::default(),
    )?
    .is_empty()
    {
        return Err(Error::new(
            "Variant selection forced alternatives for one observed strategy",
        ));
    }
    println!("Isolated strategy selection checks passed.");
    Ok(())
}

/// A hero without its own effects gets the generic build of all heroes, not no build.
fn check_fallback_build(
    effects: &EffectTable,
    catalog: &ItemCatalog,
    medians: &PurchaseMedians,
) -> Result<()> {
    let generic = effects
        .iter()
        .map(|((_, phase), value)| ((ALL_HEROES, *phase), value.clone()))
        .collect::<EffectTable>();
    if assemble_build(2, &generic, catalog, medians).is_some() {
        return Err(Error::new(
            "Build assembly used the effects of all heroes as a hero's own",
        ));
    }
    let fallback = assemble_fallback_build(2, &generic, catalog, medians).ok_or_else(|| {
        Error::new("Fallback assembly made no build from the effects of all heroes")
    })?;
    let reference = assemble_build(1, effects, catalog, medians)
        .ok_or_else(|| Error::new("Reference main build is missing"))?;
    if fallback.phase_sets != reference.phase_sets {
        return Err(Error::new(
            "Fallback assembly differs from the build of the same effects",
        ));
    }
    if assemble_fallback_build(2, effects, catalog, medians).is_some() {
        return Err(Error::new(
            "Fallback assembly made a build without the effects of all heroes",
        ));
    }
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
    for id in [1, 2, 3, 10, 11, 12, 20, 21, 22, 30, 31, 32, 40, 41, 42] {
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
                    } else if item.item_id == 22 {
                        // The shared item of the three strategies is too rare to be a key item.
                        0.02
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

/// The expensive items of three strategies that share one item, so their separation is 0.8.
const SHARED_GROUPS: [[u64; 3]; 3] = [[20, 21, 22], [30, 31, 22], [40, 41, 22]];

/// States of players who own one item group at the late phases, in one fold.
fn create_group_states(
    groups: &[[u64; 3]],
    owners: u32,
    fold: &str,
    first_match: u64,
) -> Vec<LandmarkState> {
    let mut states = Vec::new();
    for (group, items) in groups.iter().enumerate() {
        for owner in 0..owners {
            for landmark_s in PHASES {
                let mut item_ids = vec![1, 2, 3];
                if landmark_s > 540 {
                    item_ids.extend(items);
                }
                states.push(LandmarkState {
                    match_id: first_match
                        + u64::try_from(group).unwrap_or(0) * u64::from(owners)
                        + u64::from(owner),
                    player_slot: 0,
                    team_id: 0,
                    hero_id: 1,
                    fold: fold.into(),
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

/// The distinct item count and the cost share decide the selection, and the build limit holds.
fn check_separation_rule(
    effects: &EffectTable,
    catalog: &ItemCatalog,
    medians: &PurchaseMedians,
    main: &build_assembly::AssembledBuild,
) -> Result<()> {
    let states = create_group_states(&SHARED_GROUPS, 120, "development", 1000);
    let references = states.iter().collect::<Vec<_>>();
    let gates = |rule: VariantSelection| -> Result<Vec<(u64, VariantGate)>> {
        Ok(
            explain_item_variants(1, &references, effects, catalog, medians, main, rule)?
                .into_iter()
                .filter(|candidate| [20, 30, 40].contains(&candidate.item_id))
                .map(|candidate| (candidate.item_id, candidate.gate))
                .collect(),
        )
    };
    let default_rule = VariantSelection::default();
    let default_gates = gates(default_rule)?;
    if default_gates
        != [
            (20, VariantGate::Selected),
            (30, VariantGate::Selected),
            (40, VariantGate::BuildLimit),
        ]
    {
        return Err(Error::new(format!(
            "The default rule did not select two distinct strategies and stop at the limit: {default_gates:?}"
        )));
    }
    let reported = explain_item_variants(
        1,
        &references,
        effects,
        catalog,
        medians,
        main,
        default_rule,
    )?;
    let separation = |item_id: u64| {
        reported
            .iter()
            .find(|candidate| candidate.item_id == item_id)
            .and_then(|candidate| candidate.separation_minimum)
    };
    if separation(20) != Some(1.0) || separation(40).is_none_or(|value| (value - 0.8).abs() > 1e-9)
    {
        return Err(Error::new(
            "The separation report does not give the cost share of the different items",
        ));
    }
    let strict_items = VariantSelection {
        minimum_distinct_items: 3,
        ..default_rule
    };
    if gates(strict_items)?
        != [
            (20, VariantGate::Selected),
            (30, VariantGate::Similar),
            (40, VariantGate::Similar),
        ]
    {
        return Err(Error::new(
            "The distinct item count did not reject strategies that share one item",
        ));
    }
    let strict_share = VariantSelection {
        minimum_separation: 0.9,
        ..default_rule
    };
    if gates(strict_share)? != gates(strict_items)? {
        return Err(Error::new(
            "The cost share did not reject strategies with a separation of 0.8",
        ));
    }
    Ok(())
}

/// Production re-assembles a selected strategy from all folds and drops it when the test fold
/// makes it the same as an installed build.
fn check_production_drop(
    effects: &EffectTable,
    catalog: &ItemCatalog,
    medians: &PurchaseMedians,
) -> Result<()> {
    let mut states = create_group_states(&SHARED_GROUPS[..2], 120, "development", 1000);
    // Test players own the second key item with the items of the first strategy.
    states.extend(
        create_group_states(&[[20, 21, 22]], 200, "test", 5000)
            .into_iter()
            .map(|mut state| {
                if state.landmark_s > 540 {
                    state.item_ids.push(30);
                }
                state
            }),
    );
    let references = states.iter().collect::<Vec<_>>();
    let context = AssemblyContext {
        effects,
        development_effects: effects,
        catalog,
        medians,
        selection: VariantSelection::default(),
    };
    let assembly = HeroAssembly::assemble(1, &references, &context)?;
    let installed = assembly
        .variants
        .iter()
        .map(|variant| variant.build.key_item_id)
        .collect::<Vec<_>>();
    if installed != [20] || assembly.dropped != [(30, VariantGate::Similar)] || assembly.generic {
        return Err(Error::new(format!(
            "Production kept a strategy that all folds made similar: installed {installed:?}, dropped {:?}",
            assembly.dropped
        )));
    }
    Ok(())
}
