use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Result, count_as_f64};

use crate::build_assembly::{AssembledBuild, PHASES, PurchaseMedians, assemble_build};
use crate::item_effects::{
    ALL_HEROES, EffectTable, HeroLandmarkEffects, ItemCatalog, LandmarkState,
};

const MINIMUM_OWNERS: usize = 100;
pub const MINIMUM_SEPARATION: f64 = 0.30;
const MAXIMUM_ADDITIONAL_BUILDS: usize = 2;
/// The mid game and late game phases at which players must own a variant key item.
const KEY_ITEM_PHASES: [u32; 2] = [1200, 1800];
/// The hero adoption range of a variant key item at one of its phases.
const KEY_ITEM_ADOPTION: std::ops::RangeInclusive<f64> = 0.05..=0.70;

/// A build assembled from players who own its key item at 20 or 30 minutes.
#[derive(Debug)]
pub struct ItemVariant {
    pub build: AssembledBuild,
    pub owners: usize,
}

/// Selects distinct variants from development matches without using test outcomes.
///
/// Each variant needs 100 distinct player matches and two different expensive items in each direction.
/// A hero can retain only its main build when the candidates are similar or lack support.
pub fn select_item_variants(
    hero_id: u64,
    states: &[&LandmarkState],
    table: &EffectTable,
    catalog: &ItemCatalog,
    medians: &PurchaseMedians,
    main: &AssembledBuild,
) -> Result<Vec<ItemVariant>> {
    let mut candidates = Vec::new();
    for item in &catalog.items {
        if item.tier < 3
            || item.item_id == main.key_item_id
            || !has_supported_item(hero_id, item.item_id, table, catalog)
        {
            continue;
        }
        if let Some(variant) =
            assemble_item_variant(hero_id, item.item_id, states, table, catalog, medians)?
        {
            candidates.push(variant);
        }
    }
    let mut selected = Vec::<ItemVariant>::new();
    while selected.len() < MAXIMUM_ADDITIONAL_BUILDS {
        let mut best = None;
        for (index, candidate) in candidates.iter().enumerate() {
            let separation = std::iter::once(main)
                .chain(selected.iter().map(|variant| &variant.build))
                .map(|build| build_separation(build, &candidate.build, catalog))
                .fold(1.0_f64, f64::min);
            if separation < MINIMUM_SEPARATION {
                continue;
            }
            let score = separation * count_as_f64(u64::try_from(candidate.owners)?)?.sqrt();
            if best.is_none_or(|(_, previous)| score > previous) {
                best = Some((index, score));
            }
        }
        let Some((index, _)) = best else {
            break;
        };
        selected.push(candidates.remove(index));
    }
    Ok(selected)
}

fn has_supported_item(
    hero_id: u64,
    item_id: u64,
    table: &EffectTable,
    catalog: &ItemCatalog,
) -> bool {
    let Some(column) = catalog.column(item_id) else {
        return false;
    };
    KEY_ITEM_PHASES.iter().any(|phase| {
        table.get(&(hero_id, *phase)).is_some_and(|effects| {
            KEY_ITEM_ADOPTION.contains(&effects.adoption[column]) && effects.effects[column] > 0.0
        })
    })
}

/// Assembles an item variant with the same selection rule in development and production.
pub fn assemble_item_variant(
    hero_id: u64,
    item_id: u64,
    states: &[&LandmarkState],
    table: &EffectTable,
    catalog: &ItemCatalog,
    medians: &PurchaseMedians,
) -> Result<Option<ItemVariant>> {
    let owners = states
        .iter()
        .filter(|state| {
            state.hero_id == hero_id
                && KEY_ITEM_PHASES.contains(&state.landmark_s)
                && state.item_ids.contains(&item_id)
        })
        .map(|state| (state.match_id, state.player_slot))
        .collect::<BTreeSet<_>>();
    if owners.len() < MINIMUM_OWNERS {
        return Ok(None);
    }
    let selected = states
        .iter()
        .copied()
        .filter(|state| {
            state.hero_id == hero_id && owners.contains(&(state.match_id, state.player_slot))
        })
        .collect::<Vec<_>>();
    let conditioned = condition_item_adoption(hero_id, &selected, table, catalog)?;
    let Some(mut build) = assemble_build(hero_id, &conditioned, catalog, medians) else {
        return Ok(None);
    };
    if !build.core.iter().any(|item| item.item_id == item_id) {
        return Ok(None);
    }
    build.key_item_id = item_id;
    Ok(Some(ItemVariant {
        build,
        owners: owners.len(),
    }))
}

fn condition_item_adoption(
    hero_id: u64,
    states: &[&LandmarkState],
    table: &EffectTable,
    catalog: &ItemCatalog,
) -> Result<EffectTable> {
    let mut conditioned = BTreeMap::new();
    for phase in PHASES {
        let Some(effects) = table.get(&(hero_id, phase)) else {
            continue;
        };
        let rows = states
            .iter()
            .copied()
            .filter(|state| state.landmark_s == phase)
            .collect::<Vec<_>>();
        if rows.len() < MINIMUM_OWNERS {
            continue;
        }
        conditioned.insert((hero_id, phase), summarize_owners(&rows, effects, catalog)?);
        if let Some(global) = table.get(&(ALL_HEROES, phase)) {
            conditioned.insert((ALL_HEROES, phase), global.clone());
        }
    }
    Ok(conditioned)
}

fn summarize_owners(
    states: &[&LandmarkState],
    effects: &HeroLandmarkEffects,
    catalog: &ItemCatalog,
) -> Result<HeroLandmarkEffects> {
    let mut owners = vec![0_u64; catalog.items.len()];
    let mut winners = vec![0_u64; catalog.items.len()];
    let mut spends = Vec::new();
    for state in states {
        let items = state.item_ids.iter().copied().collect::<BTreeSet<_>>();
        spends.push(catalog.cost(&items));
        for item in items {
            if let Some(column) = catalog.column(item) {
                owners[column] += 1;
                winners[column] += u64::from(state.won);
            }
        }
    }
    spends.sort_unstable();
    let total = count_as_f64(u64::try_from(states.len())?)?;
    Ok(HeroLandmarkEffects {
        effects: effects.effects.clone(),
        adoption: owners
            .iter()
            .map(|count| Ok(count_as_f64(*count)? / total))
            .collect::<Result<_>>()?,
        owner_win_rates: owners
            .iter()
            .zip(winners)
            .map(|(owners, winners)| Ok(count_as_f64(winners)? / count_as_f64((*owners).max(1))?))
            .collect::<Result<_>>()?,
        median_spend: spends[spends.len() / 2],
        observations: states.len(),
    })
}

/// Returns the cost share that differs between the expensive CORE items of two builds.
#[must_use]
pub fn build_separation(
    first: &AssembledBuild,
    second: &AssembledBuild,
    catalog: &ItemCatalog,
) -> f64 {
    let expensive = |build: &AssembledBuild| {
        build
            .core
            .iter()
            .filter(|item| item.tier >= 3)
            .map(|item| item.item_id)
            .collect::<BTreeSet<_>>()
    };
    let first = expensive(first);
    let second = expensive(second);
    if first.difference(&second).count() < 2 || second.difference(&first).count() < 2 {
        return 0.0;
    }
    let union = first.union(&second).copied().collect();
    let difference = first.symmetric_difference(&second).copied().collect();
    f64::from(catalog.cost(&difference)) / f64::from(catalog.cost(&union).max(1))
}
