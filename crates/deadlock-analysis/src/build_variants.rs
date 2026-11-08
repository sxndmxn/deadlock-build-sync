use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Result, count_as_f64};

use crate::build_assembly::{AssembledBuild, PHASES, PurchaseMedians, assemble_build};
use crate::item_effects::{
    ALL_HEROES, EffectTable, HeroLandmarkEffects, ItemCatalog, LandmarkState,
};

const MINIMUM_OWNERS: usize = 100;
const MINIMUM_DISTINCT_ITEMS: usize = 2;
const MINIMUM_SEPARATION: f64 = 0.30;
const MAXIMUM_ADDITIONAL_BUILDS: usize = 2;
/// The mid game and late game phases at which players must own a variant key item.
const KEY_ITEM_PHASES: [u32; 2] = [1200, 1800];
/// The hero adoption range of a variant key item at one of its phases.
const KEY_ITEM_ADOPTION: std::ops::RangeInclusive<f64> = 0.05..=0.70;

/// The rule that separates additional builds from the main build and from each other.
///
/// Two builds are distinct when each has at least `minimum_distinct_items` expensive CORE items
/// that the other lacks, and the different items account for at least `minimum_separation` of
/// the combined unique item cost. Smaller values accept more similar additional builds.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct VariantSelection {
    pub minimum_distinct_items: usize,
    pub minimum_separation: f64,
    pub maximum_additional_builds: usize,
}

/// The rule of installed builds. See `docs/build-method.md`.
pub const DEFAULT_VARIANT_SELECTION: VariantSelection = VariantSelection {
    minimum_distinct_items: MINIMUM_DISTINCT_ITEMS,
    minimum_separation: MINIMUM_SEPARATION,
    maximum_additional_builds: MAXIMUM_ADDITIONAL_BUILDS,
};

impl VariantSelection {
    /// Returns true when the two builds are distinct under this rule.
    #[must_use]
    pub fn is_distinct(
        self,
        first: &AssembledBuild,
        second: &AssembledBuild,
        catalog: &ItemCatalog,
    ) -> bool {
        build_separation(first, second, catalog, self.minimum_distinct_items)
            >= self.minimum_separation
    }
}

/// A build assembled from players who own its key item at 20 or 30 minutes.
#[derive(Debug)]
pub struct ItemVariant {
    pub build: AssembledBuild,
    pub owners: usize,
}

/// The first gate that rejected a candidate key item, or its selection.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum VariantGate {
    /// The item is the key item of the main build.
    MainKeyItem,
    /// At both phases, the hero adoption is outside 5% to 70% or the effect is not positive.
    UnsupportedItem,
    /// Fewer than 100 distinct player matches own the item at 20 or 30 minutes.
    FewOwners,
    /// The states of the owners did not assemble a build.
    NoBuild,
    /// The assembled build does not include the item in CORE.
    KeyItemOutsideCore,
    /// The build is too similar to the main build or to a selected additional build.
    Similar,
    /// The selection reached the maximum number of additional builds.
    BuildLimit,
    /// The build was selected.
    Selected,
}

impl VariantGate {
    #[must_use]
    pub const fn name(self) -> &'static str {
        match self {
            Self::MainKeyItem => "main_key_item",
            Self::UnsupportedItem => "unsupported_item",
            Self::FewOwners => "few_owners",
            Self::NoBuild => "no_build",
            Self::KeyItemOutsideCore => "key_item_outside_core",
            Self::Similar => "similar",
            Self::BuildLimit => "build_limit",
            Self::Selected => "selected",
        }
    }
}

/// One Tier 3 or Tier 4 item of a hero and the gate result of its build.
#[derive(Clone, Debug)]
pub struct VariantCandidate {
    pub item_id: u64,
    /// The hero adoption at 20 and 30 minutes.
    pub adoption: [f64; 2],
    /// The hero effect at 20 and 30 minutes.
    pub effect: [f64; 2],
    /// The distinct player matches that own the item at 20 or 30 minutes.
    pub owners: usize,
    /// The separation from the main build, when the owners assembled a build.
    pub separation_main: Option<f64>,
    /// The smallest separation from the main build and the selected builds at the last comparison.
    pub separation_minimum: Option<f64>,
    pub gate: VariantGate,
}

impl VariantCandidate {
    /// Records a gate when no earlier gate rejected the item.
    fn reject(&mut self, gate: VariantGate) {
        if self.gate == VariantGate::Selected {
            self.gate = gate;
        }
    }
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
    select_item_variants_with_rule(
        hero_id,
        states,
        table,
        catalog,
        medians,
        main,
        DEFAULT_VARIANT_SELECTION,
    )
}

/// Selects distinct variants with a specified separation rule.
pub fn select_item_variants_with_rule(
    hero_id: u64,
    states: &[&LandmarkState],
    table: &EffectTable,
    catalog: &ItemCatalog,
    medians: &PurchaseMedians,
    main: &AssembledBuild,
    rule: VariantSelection,
) -> Result<Vec<ItemVariant>> {
    let (_, selected) =
        evaluate_item_variants(hero_id, states, table, catalog, medians, main, rule)?;
    Ok(selected)
}

/// Reports the gate result of every Tier 3 or Tier 4 item of a hero.
///
/// The report uses the same gates as `select_item_variants_with_rule`.
pub fn explain_item_variants(
    hero_id: u64,
    states: &[&LandmarkState],
    table: &EffectTable,
    catalog: &ItemCatalog,
    medians: &PurchaseMedians,
    main: &AssembledBuild,
    rule: VariantSelection,
) -> Result<Vec<VariantCandidate>> {
    let (candidates, _) =
        evaluate_item_variants(hero_id, states, table, catalog, medians, main, rule)?;
    Ok(candidates)
}

/// Assembles every candidate, then selects additional builds in order of separation and support.
fn evaluate_item_variants(
    hero_id: u64,
    states: &[&LandmarkState],
    table: &EffectTable,
    catalog: &ItemCatalog,
    medians: &PurchaseMedians,
    main: &AssembledBuild,
    rule: VariantSelection,
) -> Result<(Vec<VariantCandidate>, Vec<ItemVariant>)> {
    let mut candidates = Vec::new();
    let mut builds = BTreeMap::new();
    for item in &catalog.items {
        if item.tier < 3 {
            continue;
        }
        let (mut candidate, variant) =
            describe_item_variant(hero_id, item.item_id, states, table, catalog, medians)?;
        if item.item_id == main.key_item_id {
            candidate.gate = VariantGate::MainKeyItem;
        } else if let Some(variant) = variant.filter(|_| candidate.gate == VariantGate::Selected) {
            candidate.separation_main = Some(build_separation(
                main,
                &variant.build,
                catalog,
                rule.minimum_distinct_items,
            ));
            builds.insert(item.item_id, variant);
        }
        candidates.push(candidate);
    }
    let selected = select_distinct_variants(&mut candidates, builds, main, catalog, rule);
    Ok((candidates, selected))
}

/// Selects the candidate with the largest separation times the square root of its owners, repeatedly.
fn select_distinct_variants(
    candidates: &mut [VariantCandidate],
    mut builds: BTreeMap<u64, ItemVariant>,
    main: &AssembledBuild,
    catalog: &ItemCatalog,
    rule: VariantSelection,
) -> Vec<ItemVariant> {
    let mut selected = Vec::<ItemVariant>::new();
    while selected.len() < rule.maximum_additional_builds {
        let mut best: Option<(u64, f64)> = None;
        for candidate in candidates.iter_mut() {
            let Some(variant) = builds.get(&candidate.item_id) else {
                continue;
            };
            let separation = std::iter::once(main)
                .chain(selected.iter().map(|variant| &variant.build))
                .map(|build| {
                    build_separation(build, &variant.build, catalog, rule.minimum_distinct_items)
                })
                .fold(1.0_f64, f64::min);
            candidate.separation_minimum = Some(separation);
            if separation < rule.minimum_separation {
                candidate.gate = VariantGate::Similar;
                continue;
            }
            candidate.gate = VariantGate::BuildLimit;
            let score = separation * owner_weight(variant.owners);
            if best.is_none_or(|(_, previous)| score > previous) {
                best = Some((candidate.item_id, score));
            }
        }
        let Some((item_id, _)) = best else {
            break;
        };
        if let Some(candidate) = candidates
            .iter_mut()
            .find(|candidate| candidate.item_id == item_id)
        {
            candidate.gate = VariantGate::Selected;
        }
        if let Some(variant) = builds.remove(&item_id) {
            selected.push(variant);
        }
    }
    selected
}

/// Returns the square root of the owner count. The count fits in `f64` without loss.
fn owner_weight(owners: usize) -> f64 {
    u32::try_from(owners).map_or(f64::MAX, |owners| f64::from(owners).sqrt())
}

/// Assembles the build of the players who own an item, with the owner and assembly gates only.
///
/// Development selection also applies the support gate. Production re-assembles a selected
/// item from all folds without it, so the all-fold effects cannot drop a selected strategy.
pub fn assemble_item_variant(
    hero_id: u64,
    item_id: u64,
    states: &[&LandmarkState],
    table: &EffectTable,
    catalog: &ItemCatalog,
    medians: &PurchaseMedians,
) -> Result<Option<ItemVariant>> {
    let (_, variant) = describe_item_variant(hero_id, item_id, states, table, catalog, medians)?;
    Ok(variant)
}

/// Applies the support, owner, and assembly gates to one item and returns the result.
///
/// The variant is `Some` when the item passes the owner and assembly gates. The gate names
/// the first gate that rejected the item, so an unsupported item can still have a variant.
pub fn describe_item_variant(
    hero_id: u64,
    item_id: u64,
    states: &[&LandmarkState],
    table: &EffectTable,
    catalog: &ItemCatalog,
    medians: &PurchaseMedians,
) -> Result<(VariantCandidate, Option<ItemVariant>)> {
    let column = catalog.column(item_id);
    let phase_value = |values: fn(&HeroLandmarkEffects) -> &Vec<f64>| {
        KEY_ITEM_PHASES.map(|phase| {
            column
                .and_then(|column| {
                    table
                        .get(&(hero_id, phase))
                        .map(|effects| values(effects)[column])
                })
                .unwrap_or(0.0)
        })
    };
    let mut candidate = VariantCandidate {
        item_id,
        adoption: phase_value(|effects| &effects.adoption),
        effect: phase_value(|effects| &effects.effects),
        owners: 0,
        separation_main: None,
        separation_minimum: None,
        gate: VariantGate::Selected,
    };
    let supported = candidate
        .adoption
        .iter()
        .zip(&candidate.effect)
        .any(|(adoption, effect)| KEY_ITEM_ADOPTION.contains(adoption) && *effect > 0.0);
    let owners = states
        .iter()
        .filter(|state| {
            state.hero_id == hero_id
                && KEY_ITEM_PHASES.contains(&state.landmark_s)
                && state.item_ids.contains(&item_id)
        })
        .map(|state| (state.match_id, state.player_slot))
        .collect::<BTreeSet<_>>();
    candidate.owners = owners.len();
    if !supported {
        candidate.gate = VariantGate::UnsupportedItem;
    }
    if owners.len() < MINIMUM_OWNERS {
        candidate.reject(VariantGate::FewOwners);
        return Ok((candidate, None));
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
        candidate.reject(VariantGate::NoBuild);
        return Ok((candidate, None));
    };
    if !build.core.iter().any(|item| item.item_id == item_id) {
        candidate.reject(VariantGate::KeyItemOutsideCore);
        return Ok((candidate, None));
    }
    build.key_item_id = item_id;
    Ok((
        candidate,
        Some(ItemVariant {
            build,
            owners: owners.len(),
        }),
    ))
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
///
/// The share is 0 when either build has fewer than `minimum_distinct_items` expensive CORE
/// items that the other build lacks.
#[must_use]
pub fn build_separation(
    first: &AssembledBuild,
    second: &AssembledBuild,
    catalog: &ItemCatalog,
    minimum_distinct_items: usize,
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
    if first.difference(&second).count() < minimum_distinct_items
        || second.difference(&first).count() < minimum_distinct_items
    {
        return 0.0;
    }
    let union = first.union(&second).copied().collect();
    let difference = first.symmetric_difference(&second).copied().collect();
    f64::from(catalog.cost(&difference)) / f64::from(catalog.cost(&union).max(1))
}
