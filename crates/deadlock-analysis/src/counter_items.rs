use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Error, Result, count_as_f64};
use deadlock_guides::{
    BuildItem, CounterEvidence, CounterPanel, CounterPhase, CounterTarget, HeroBuild,
    MAXIMUM_COUNTER_ITEMS,
};

use crate::build_assembly::{PurchaseMedians, describe_item};
use crate::item_effects::{
    COVARIATES, DEFAULT_PENALTIES, EffectTable, ItemCatalog, LandmarkState, build_feature_row,
};
use crate::ridge_logistic::fit_ridge_logistic;

/// The item class names of each counter group.
///
/// Experiments E6 and E9 in `docs/research-log.md` tested these groups on four patches.
const COUNTER_GROUPS: [(CounterTarget, &[&str]); 3] = [
    (
        CounterTarget::Weapon,
        &[
            "upgrade_regenerating_bullet_shield",
            "upgrade_weapon_shielding",
            "upgrade_improved_bullet_armor",
            "upgrade_metal_skin",
            "upgrade_deflecting_armor",
            "upgrade_return_fire",
        ],
    ),
    (
        CounterTarget::Spirit,
        &["upgrade_spirit_bubble", "upgrade_tech_purge"],
    ),
    (
        CounterTarget::Sustain,
        &[
            "upgrade_healbane",
            "upgrade_toxic_bullets",
            "upgrade_rupture",
            "upgrade_banshee_slugs",
            "upgrade_inhibitor",
            "upgrade_spirit_burn",
        ],
    ),
];
/// The healing and lifesteal item class names that define the enemy sustain condition.
const SUSTAIN_ITEMS: [&str; 14] = [
    "upgrade_vampire",
    "upgrade_health_stealing_magic",
    "upgrade_damage_recycler",
    "upgrade_siphon_bullets",
    "upgrade_health_stimpak",
    "upgrade_healing_booster",
    "upgrade_restorative_locket",
    "upgrade_health_nova",
    "upgrade_healbuff",
    "upgrade_rescue_beam",
    "upgrade_lifestrike_gauntlets",
    "upgrade_boxing_glove",
    "upgrade_surging_power",
    "upgrade_endurance",
];
/// The mid game and late game landmarks. The counter effect did not replicate in the lane phase.
pub const COUNTER_PHASES: [u32; 2] = [1200, 1800];
/// The standard deviation of the enemy spirit share is near 0.06.
/// This factor gives the condition a standard deviation near 1.
pub const CONDITION_SCALE: f64 = 16.0;
/// The smallest hero adoption at a counter phase for an item in a counter panel.
const MINIMUM_PANEL_ADOPTION: f64 = 0.01;

/// The counter item groups that exist in the current shop.
#[derive(Debug)]
pub struct CounterGroups {
    groups: Vec<(CounterTarget, BTreeSet<u64>)>,
    sustain_items: BTreeSet<u64>,
}

impl CounterGroups {
    /// Finds the group items in the shop. Items that a patch removed are left out.
    /// The sustain group is left out when the shop has no sustain condition items.
    #[must_use]
    pub fn from_catalog(catalog: &ItemCatalog) -> Self {
        let sustain_items = find_classes(catalog, &SUSTAIN_ITEMS);
        let groups = COUNTER_GROUPS
            .iter()
            .map(|(target, class_names)| (*target, find_classes(catalog, class_names)))
            .filter(|(target, items)| {
                !items.is_empty()
                    && (*target != CounterTarget::Sustain || !sustain_items.is_empty())
            })
            .collect();
        Self {
            groups,
            sustain_items,
        }
    }
}

impl CounterGroups {
    /// Returns the items of each group, in the group order.
    #[must_use]
    pub fn item_groups(&self) -> Vec<&BTreeSet<u64>> {
        self.groups.iter().map(|(_, items)| items).collect()
    }

    /// Returns the healing and lifesteal items that define the enemy sustain condition.
    #[must_use]
    pub const fn sustain_items(&self) -> &BTreeSet<u64> {
        &self.sustain_items
    }
}

fn find_classes(catalog: &ItemCatalog, class_names: &[&str]) -> BTreeSet<u64> {
    catalog
        .items
        .iter()
        .filter(|item| class_names.contains(&item.class_name.as_str()))
        .map(|item| item.item_id)
        .collect()
}

/// The coefficient and match-clustered standard error of one item group interaction.
#[derive(Clone, Copy, Debug)]
pub struct GroupInteraction {
    pub coefficient: f64,
    pub standard_error: f64,
}

/// Returns the standardized enemy spirit share of each state.
#[must_use]
pub fn spirit_conditions(states: &[&LandmarkState], spirit_mean: f64) -> Vec<f64> {
    states
        .iter()
        .map(|state| (state.enemy_spirit_share - spirit_mean) * CONDITION_SCALE)
        .collect()
}

/// Fits one global model at one landmark with match conditions and item group interactions.
///
/// Each condition has one standardized value for each state. For each condition, the model adds
/// a main term and one term for each group: the number of owned group items multiplied by the
/// condition. A positive coefficient means that the group wins more when the condition is higher.
/// The result holds the interactions of the first condition for each group, then of the next condition.
///
/// # Errors
/// Returns an error when a condition has the wrong value count, or when the model fails.
pub fn fit_group_interactions(
    states: &[&LandmarkState],
    catalog: &ItemCatalog,
    groups: &[&BTreeSet<u64>],
    conditions: &[&[f64]],
    hero_terms: bool,
) -> Result<Vec<GroupInteraction>> {
    if conditions.iter().any(|values| values.len() != states.len()) {
        return Err(Error::new(
            "Each condition requires one value for each state",
        ));
    }
    let items = catalog.items.len();
    let block = 1 + groups.len();
    let hero_ids = states
        .iter()
        .map(|state| state.hero_id)
        .collect::<BTreeSet<_>>()
        .into_iter()
        .skip(1)
        .collect::<Vec<_>>();
    let hero_base = COVARIATES + items + conditions.len() * block;
    let hero_block = 1 + conditions.len();
    let width = if hero_terms {
        hero_base + hero_ids.len() * hero_block
    } else {
        hero_base
    };
    let penalty = (0..width)
        .map(|index| {
            if (COVARIATES..COVARIATES + items).contains(&index) {
                DEFAULT_PENALTIES.global_item
            } else {
                1.0
            }
        })
        .collect::<Vec<_>>();
    let rows = states
        .iter()
        .enumerate()
        .map(|(row_index, state)| {
            let mut row = build_feature_row(state, catalog);
            let owned = groups
                .iter()
                .map(|group| {
                    count_as_f64(u64::try_from(
                        state
                            .item_ids
                            .iter()
                            .filter(|item| group.contains(item))
                            .count(),
                    )?)
                })
                .collect::<Result<Vec<_>>>()?;
            for (condition_index, values) in conditions.iter().enumerate() {
                let condition = values[row_index];
                let base = COVARIATES + items + condition_index * block;
                row.features.push((base, condition));
                for (offset, count) in owned.iter().enumerate() {
                    if *count > 0.0 {
                        row.features.push((base + 1 + offset, condition * count));
                    }
                }
            }
            if let Some(position) = hero_ids
                .iter()
                .position(|hero| *hero == state.hero_id)
                .filter(|_| hero_terms)
            {
                let base = hero_base + position * hero_block;
                row.features.push((base, 1.0));
                for (condition_index, values) in conditions.iter().enumerate() {
                    row.features
                        .push((base + 1 + condition_index, values[row_index]));
                }
            }
            Ok(row)
        })
        .collect::<Result<Vec<_>>>()?;
    let references = rows.iter().collect::<Vec<_>>();
    let matches = states
        .iter()
        .map(|state| state.match_id)
        .collect::<Vec<_>>();
    let fit = fit_ridge_logistic(&references, &vec![0.0; width], &penalty)?;
    (0..conditions.len())
        .flat_map(|condition_index| {
            (0..groups.len())
                .map(move |offset| COVARIATES + items + condition_index * block + 1 + offset)
        })
        .map(|index| {
            Ok(GroupInteraction {
                coefficient: fit.coefficients[index],
                standard_error: fit.clustered_standard_error(index, &references, &matches)?,
            })
        })
        .collect()
}

/// Returns the mean enemy spirit share of the states.
///
/// # Errors
/// Returns an error when the state count cannot be converted.
pub fn mean_enemy_spirit_share(states: &[&LandmarkState]) -> Result<f64> {
    Ok(states
        .iter()
        .map(|state| state.enemy_spirit_share)
        .sum::<f64>()
        / count_as_f64(u64::try_from(states.len().max(1))?)?)
}

/// Tests each counter group at each counter phase with all matches of the run.
///
/// The evidence keeps a group unless a phase contradicts its counter effect.
/// The model has hero terms, so it compares players of the same hero (E31).
///
/// # Errors
/// Returns an error when a model cannot be fitted.
pub fn estimate_counter_evidence(
    states: &[&LandmarkState],
    catalog: &ItemCatalog,
    groups: &CounterGroups,
) -> Result<Vec<CounterEvidence>> {
    let mut evidence = measure_counter_groups(states, catalog, groups, true)?;
    evidence.retain(CounterEvidence::is_supported);
    Ok(evidence)
}

/// Measures each counter group at each counter phase, in the direction of its damage type.
///
/// The weapon group coefficient changes sign, because a low spirit share means more weapon damage.
/// With hero terms, the model compares players of the same hero only.
///
/// # Errors
/// Returns an error when a model cannot be fitted.
pub fn measure_counter_groups(
    states: &[&LandmarkState],
    catalog: &ItemCatalog,
    groups: &CounterGroups,
    hero_terms: bool,
) -> Result<Vec<CounterEvidence>> {
    let spirit_mean = mean_enemy_spirit_share(states)?;
    let item_groups = groups
        .groups
        .iter()
        .map(|(_, items)| items)
        .collect::<Vec<_>>();
    let mut evidence = groups
        .groups
        .iter()
        .map(|(target, _)| CounterEvidence {
            target: *target,
            phases: Vec::new(),
        })
        .collect::<Vec<_>>();
    for phase_s in COUNTER_PHASES {
        let phase_states = states
            .iter()
            .copied()
            .filter(|state| state.landmark_s == phase_s)
            .collect::<Vec<_>>();
        if phase_states.is_empty() {
            return Ok(Vec::new());
        }
        let spirit = spirit_conditions(&phase_states, spirit_mean);
        let sustain = enemy_item_conditions(&phase_states, catalog, &groups.sustain_items)?;
        let interactions = fit_group_interactions(
            &phase_states,
            catalog,
            &item_groups,
            &[&spirit, &sustain],
            hero_terms,
        )?;
        let (spirit_block, sustain_block) = interactions.split_at(item_groups.len());
        for (index, group) in evidence.iter_mut().enumerate() {
            let (direction, interaction) = match group.target {
                CounterTarget::Spirit => (1.0, spirit_block[index]),
                CounterTarget::Weapon => (-1.0, spirit_block[index]),
                CounterTarget::Sustain => (1.0, sustain_block[index]),
            };
            group.phases.push(CounterPhase {
                phase_s,
                coefficient: direction * interaction.coefficient,
                standard_error: interaction.standard_error,
                observations: u64::try_from(phase_states.len())?,
            });
        }
    }
    Ok(evidence)
}

/// Returns the standardized share of enemy item cost in the condition items, for each state.
///
/// The share divides the cost of condition items that the enemy players own at the landmark
/// by the cost of all items that they own. A share describes the enemy build without its wealth.
/// The states must belong to one landmark. The values have mean 0 and standard deviation 1.
///
/// # Errors
/// Returns an error when the state count cannot be converted.
pub fn enemy_item_conditions(
    states: &[&LandmarkState],
    catalog: &ItemCatalog,
    items: &BTreeSet<u64>,
) -> Result<Vec<f64>> {
    let mut team_costs = BTreeMap::<(u64, i32), [f64; 2]>::new();
    let mut match_costs = BTreeMap::<u64, [f64; 2]>::new();
    for state in states {
        let mut costs = [0.0, 0.0];
        for asset in state
            .item_ids
            .iter()
            .filter_map(|item| catalog.asset(*item))
        {
            let cost = f64::from(asset.cost);
            costs[1] += cost;
            if items.contains(&asset.item_id) {
                costs[0] += cost;
            }
        }
        for total in [
            team_costs
                .entry((state.match_id, state.team_id))
                .or_default(),
            match_costs.entry(state.match_id).or_default(),
        ] {
            total[0] += costs[0];
            total[1] += costs[1];
        }
    }
    let shares = states
        .iter()
        .map(|state| {
            let all = match_costs
                .get(&state.match_id)
                .copied()
                .unwrap_or_default();
            let own = team_costs
                .get(&(state.match_id, state.team_id))
                .copied()
                .unwrap_or_default();
            (all[0] - own[0]) / (all[1] - own[1]).max(1.0)
        })
        .collect::<Vec<_>>();
    let count = count_as_f64(u64::try_from(shares.len().max(1))?)?;
    let mean = shares.iter().sum::<f64>() / count;
    let deviation = (shares
        .iter()
        .map(|share| (share - mean).powi(2))
        .sum::<f64>()
        / count)
        .sqrt()
        .max(1e-9);
    Ok(shares
        .iter()
        .map(|share| (share - mean) / deviation)
        .collect())
}

/// Selects the counter items that this hero buys, for each group with run evidence.
///
/// A panel holds group items outside CORE with a hero adoption of at least 1% at a counter phase.
/// The panel orders items by adoption and holds at most four items.
#[must_use]
pub fn select_counter_panels(
    build: &HeroBuild,
    table: &EffectTable,
    catalog: &ItemCatalog,
    medians: &PurchaseMedians,
    groups: &CounterGroups,
    evidence: &[CounterEvidence],
) -> Vec<CounterPanel> {
    groups
        .groups
        .iter()
        .filter(|(target, _)| evidence.iter().any(|group| group.target == *target))
        .filter_map(|(target, items)| {
            let mut candidates = items
                .iter()
                .filter(|item| !build.core.iter().any(|core| core.item_id == **item))
                .filter_map(|item| {
                    select_counter_item(build.hero_id, *item, table, catalog, medians)
                })
                .collect::<Vec<_>>();
            candidates.sort_by(|first, second| {
                second
                    .adoption
                    .total_cmp(&first.adoption)
                    .then(first.item_id.cmp(&second.item_id))
            });
            candidates.truncate(MAXIMUM_COUNTER_ITEMS);
            (!candidates.is_empty()).then_some(CounterPanel {
                target: *target,
                items: candidates,
            })
        })
        .collect()
}

/// Describes the item at the counter phase where this hero owns it most often.
fn select_counter_item(
    hero_id: u64,
    item_id: u64,
    table: &EffectTable,
    catalog: &ItemCatalog,
    medians: &PurchaseMedians,
) -> Option<BuildItem> {
    COUNTER_PHASES
        .iter()
        .filter_map(|phase| describe_item(hero_id, item_id, *phase, table, catalog, medians))
        .filter(|item| item.adoption >= MINIMUM_PANEL_ADOPTION)
        .max_by(|first, second| first.adoption.total_cmp(&second.adoption))
}
