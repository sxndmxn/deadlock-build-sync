use std::collections::{BTreeMap, BTreeSet};

use deadlock_guides::BuildItem;

use crate::item_effects::{ALL_HEROES, EffectTable, HeroLandmarkEffects, ItemCatalog};

/// Phase landmarks: lane (9 minutes), mid game (20 minutes), and late game (30 minutes).
pub const PHASES: [u32; 3] = [540, 1200, 1800];
/// The smallest share of hero players who own an item at a phase before CORE can use it.
const MINIMUM_ADOPTION: f64 = 0.03;
/// One effect step of this size equals a factor of e in adoption in the item score.
const EFFECT_SCALE: f64 = 0.05;
/// The effect scale of the key item value. E14 tested only the CORE item score.
const KEY_ITEM_EFFECT_SCALE: f64 = 0.1;
const MAXIMUM_OWNED: usize = 12;
const SITUATIONAL_MINIMUM_EFFECT: f64 = 0.02;
const SITUATIONAL_ITEMS_PER_TIER: usize = 6;

/// Median first purchase time and net worth for one hero and item.
///
/// The soul window is the middle half of the net worth values at the first purchase.
#[derive(Clone, Copy, Debug)]
pub struct PurchaseMedian {
    pub buy_time_s: f64,
    pub net_worth: u32,
    pub soul_window: [u32; 2],
}

pub type PurchaseMedians = BTreeMap<(u64, u64), PurchaseMedian>;

/// The items that a build owns at each phase landmark.
pub type PhaseSets = BTreeMap<u32, BTreeSet<u64>>;

/// The CORE purchase order and the items the build owns at each phase.
#[derive(Clone, Debug)]
pub struct AssembledBuild {
    pub core: Vec<BuildItem>,
    pub phase_sets: PhaseSets,
    pub situational: Vec<BuildItem>,
    pub key_item_id: u64,
}

/// The item score rule: `ln(adoption / 0.03) + effect / effect_scale`.
///
/// A smaller effect scale moves the choice more toward items that win more.
/// An infinite effect scale removes the effect term and selects by adoption only.
/// Items with an adoption below the adoption floor cannot enter the build.
#[derive(Clone, Copy, Debug)]
pub struct ItemScoring {
    pub effect_scale: f64,
    pub adoption_floor: f64,
}

impl std::str::FromStr for ItemScoring {
    type Err = deadlock_data::Error;

    /// Reads `SCALE` or `SCALE:FLOOR`. The scale is positive, and `inf` selects by adoption only.
    fn from_str(text: &str) -> deadlock_data::Result<Self> {
        let invalid = || {
            deadlock_data::Error::new(format!(
                "Score rule must be SCALE or SCALE:FLOOR with a positive scale: {text}"
            ))
        };
        let (scale, floor) = text.split_once(':').unwrap_or((text, "0"));
        let effect_scale = scale
            .parse::<f64>()
            .ok()
            .filter(|scale| *scale > 0.0)
            .ok_or_else(invalid)?;
        let adoption_floor = floor
            .parse::<f64>()
            .ok()
            .filter(|floor| (0.0..1.0).contains(floor))
            .ok_or_else(invalid)?;
        Ok(Self {
            effect_scale,
            adoption_floor,
        })
    }
}

/// The item score rule of installed builds.
pub const DEFAULT_SCORING: ItemScoring = ItemScoring {
    effect_scale: EFFECT_SCALE,
    adoption_floor: MINIMUM_ADOPTION,
};

impl ItemScoring {
    /// Scores an item by adoption, tilted toward items with a positive win effect.
    ///
    /// The logarithm keeps the build close to items that players at this rank use.
    /// The effect term moves the choice toward items that win more in similar states.
    fn score_item(self, effects: &HeroLandmarkEffects, column: usize) -> f64 {
        if effects.adoption[column] < self.adoption_floor {
            return f64::NEG_INFINITY;
        }
        (effects.adoption[column] / MINIMUM_ADOPTION).ln()
            + effects.effects[column] / self.effect_scale
    }
}

/// Assembles a build phase by phase within the hero's median item spend.
#[must_use]
pub fn assemble_build(
    hero_id: u64,
    table: &EffectTable,
    catalog: &ItemCatalog,
    medians: &PurchaseMedians,
) -> Option<AssembledBuild> {
    assemble_build_with_scoring(hero_id, table, catalog, medians, DEFAULT_SCORING)
}

/// Assembles a build with a specified item score rule.
#[must_use]
pub fn assemble_build_with_scoring(
    hero_id: u64,
    table: &EffectTable,
    catalog: &ItemCatalog,
    medians: &PurchaseMedians,
    scoring: ItemScoring,
) -> Option<AssembledBuild> {
    let mut owned = BTreeSet::new();
    let mut added = Vec::new();
    let mut phase_sets = BTreeMap::new();
    for phase in PHASES {
        let Some(effects) = table.get(&(hero_id, phase)) else {
            continue;
        };
        owned = advance_phase(&owned, effects, catalog, scoring, &mut added, phase);
        phase_sets.insert(phase, owned.clone());
    }
    if added.is_empty() {
        return None;
    }
    let mut core = added
        .iter()
        .filter_map(|(phase, item)| describe_item(hero_id, *item, *phase, table, catalog, medians))
        .collect::<Vec<_>>();
    let buy_time = |item: &BuildItem| {
        medians
            .get(&(hero_id, item.item_id))
            .map_or(f64::MAX, |median| median.buy_time_s)
    };
    core.sort_by(|first, second| {
        first
            .median_net_worth
            .cmp(&second.median_net_worth)
            .then(buy_time(first).total_cmp(&buy_time(second)))
    });
    let key_item_id = select_key_item(&core, table, catalog)?;
    let situational = select_situational(hero_id, &core, table, catalog, medians);
    Some(AssembledBuild {
        core,
        phase_sets,
        situational,
        key_item_id,
    })
}

fn advance_phase(
    previous: &BTreeSet<u64>,
    effects: &HeroLandmarkEffects,
    catalog: &ItemCatalog,
    scoring: ItemScoring,
    added: &mut Vec<(u32, u64)>,
    phase: u32,
) -> BTreeSet<u64> {
    let score = |item: u64| {
        catalog
            .column(item)
            .map_or(f64::MIN, |column| scoring.score_item(effects, column))
    };
    let mut owned = previous
        .iter()
        .copied()
        .filter(|item| score(*item) > 0.0)
        .collect::<BTreeSet<_>>();
    let mut candidates = catalog
        .items
        .iter()
        .map(|asset| asset.item_id)
        .filter(|item| !owned.contains(item) && score(*item) > 0.0)
        .collect::<Vec<_>>();
    candidates.sort_by(|first, second| {
        score(*second)
            .total_cmp(&score(*first))
            .then(first.cmp(second))
    });
    for item in candidates {
        let mut next = owned.clone();
        for component in catalog.components.get(&item).into_iter().flatten() {
            next.remove(component);
        }
        next.insert(item);
        if catalog.cost(&next) <= effects.median_spend && next.len() <= MAXIMUM_OWNED {
            owned = next;
            if !added.iter().any(|(_, existing)| *existing == item) {
                added.push((phase, item));
            }
        }
    }
    owned
}

/// Describes one item with the hero's adoption and effect at one phase and its purchase medians.
#[must_use]
pub fn describe_item(
    hero_id: u64,
    item: u64,
    phase: u32,
    table: &EffectTable,
    catalog: &ItemCatalog,
    medians: &PurchaseMedians,
) -> Option<BuildItem> {
    let asset = catalog.asset(item)?;
    let column = catalog.column(item)?;
    let effects = table.get(&(hero_id, phase))?;
    let median = medians.get(&(hero_id, item));
    Some(BuildItem {
        item_id: item,
        name: asset.item_name.clone(),
        tier: asset.tier,
        cost: asset.cost,
        phase_s: phase,
        adoption: effects.adoption[column],
        win_rate: effects.owner_win_rates[column],
        statistics: None,
        effect: effects.effects[column],
        median_net_worth: median.map_or(0, |median| median.net_worth),
        soul_window: median.map_or([0, 0], |median| median.soul_window),
        imbue_target: None,
    })
}

/// Selects the Tier 3 or Tier 4 CORE item that defines the build.
///
/// The value combines the item effect with its lift: the hero's adoption divided by
/// the adoption across all heroes. Lift prefers items that this hero uses more than
/// other heroes over items that every hero buys.
fn select_key_item(core: &[BuildItem], table: &EffectTable, catalog: &ItemCatalog) -> Option<u64> {
    let late = core
        .iter()
        .filter(|item| item.tier >= 3)
        .collect::<Vec<_>>();
    let pool = if late.is_empty() {
        core.iter().collect()
    } else {
        late
    };
    let value = |item: &BuildItem| {
        let global = catalog
            .column(item.item_id)
            .and_then(|column| {
                table
                    .get(&(ALL_HEROES, item.phase_s))
                    .map(|effects| effects.adoption[column])
            })
            .unwrap_or(item.adoption);
        item.effect / KEY_ITEM_EFFECT_SCALE + (item.adoption / global.max(1e-6)).ln()
    };
    pool.into_iter()
        .max_by(|first, second| value(first).total_cmp(&value(second)))
        .map(|item| item.item_id)
}

/// Selects positive-effect items outside CORE, at the phase where each item is most common.
fn select_situational(
    hero_id: u64,
    core: &[BuildItem],
    table: &EffectTable,
    catalog: &ItemCatalog,
    medians: &PurchaseMedians,
) -> Vec<BuildItem> {
    let excluded = core
        .iter()
        .flat_map(|item| {
            std::iter::once(item.item_id).chain(
                catalog
                    .components
                    .get(&item.item_id)
                    .into_iter()
                    .flatten()
                    .copied(),
            )
        })
        .collect::<BTreeSet<_>>();
    let mut by_tier = BTreeMap::<u8, Vec<BuildItem>>::new();
    for asset in &catalog.items {
        if excluded.contains(&asset.item_id) {
            continue;
        }
        let Some(phase) = select_common_phase(hero_id, asset.item_id, table, catalog) else {
            continue;
        };
        if let Some(item) = describe_item(hero_id, asset.item_id, phase, table, catalog, medians)
            && item.adoption >= MINIMUM_ADOPTION / 2.0
            && item.effect > SITUATIONAL_MINIMUM_EFFECT
        {
            by_tier.entry(item.tier).or_default().push(item);
        }
    }
    by_tier
        .into_values()
        .flat_map(|mut items| {
            items.sort_by(|first, second| second.effect.total_cmp(&first.effect));
            items.truncate(SITUATIONAL_ITEMS_PER_TIER);
            items
        })
        .collect()
}

fn select_common_phase(
    hero_id: u64,
    item: u64,
    table: &EffectTable,
    catalog: &ItemCatalog,
) -> Option<u32> {
    let column = catalog.column(item)?;
    PHASES
        .iter()
        .filter_map(|phase| {
            table
                .get(&(hero_id, *phase))
                .map(|effects| (*phase, effects.adoption[column]))
        })
        .max_by(|first, second| first.1.total_cmp(&second.1))
        .map(|(phase, _)| phase)
}
