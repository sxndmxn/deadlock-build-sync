use std::collections::BTreeSet;

use deadlock_data::{Result, count_as_f64};
use deadlock_guides::{
    BuildItem, CounterEvidence, CounterPanel, CounterPhase, DamageType, HeroBuild,
    MAXIMUM_COUNTER_ITEMS,
};

use crate::build_assembly::{PurchaseMedians, describe_item};
use crate::item_effects::{
    COVARIATES, DEFAULT_PENALTIES, EffectTable, ItemCatalog, LandmarkState, build_feature_row,
};
use crate::ridge_logistic::fit_ridge_logistic;

/// The defensive item class names of each counter group.
///
/// Experiment E6 in `docs/research-log.md` selected these items and confirmed them on a held-out patch.
const COUNTER_GROUPS: [(DamageType, &[&str]); 2] = [
    (
        DamageType::Weapon,
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
        DamageType::Spirit,
        &["upgrade_spirit_bubble", "upgrade_tech_purge"],
    ),
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
    groups: Vec<(DamageType, BTreeSet<u64>)>,
}

impl CounterGroups {
    /// Finds the group items in the shop. Items that a patch removed are left out.
    #[must_use]
    pub fn from_catalog(catalog: &ItemCatalog) -> Self {
        let groups = COUNTER_GROUPS
            .iter()
            .map(|(damage_type, class_names)| {
                let items = catalog
                    .items
                    .iter()
                    .filter(|item| class_names.contains(&item.class_name.as_str()))
                    .map(|item| item.item_id)
                    .collect::<BTreeSet<_>>();
                (*damage_type, items)
            })
            .filter(|(_, items)| !items.is_empty())
            .collect();
        Self { groups }
    }
}

/// The coefficient and match-clustered standard error of one item group interaction.
#[derive(Clone, Copy, Debug)]
pub struct GroupInteraction {
    pub coefficient: f64,
    pub standard_error: f64,
}

/// Fits one global model at one landmark with the enemy spirit share and item group interactions.
///
/// The model adds a main term for the standardized enemy spirit share and one term for each group:
/// the number of owned group items multiplied by that condition. A positive coefficient means that
/// the group wins more against enemy teams with more spirit damage.
///
/// # Errors
/// Returns an error when the model cannot be fitted.
pub fn fit_group_interactions(
    states: &[&LandmarkState],
    catalog: &ItemCatalog,
    groups: &[&BTreeSet<u64>],
    spirit_mean: f64,
) -> Result<Vec<GroupInteraction>> {
    let items = catalog.items.len();
    let width = COVARIATES + items + 1 + groups.len();
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
        .map(|state| {
            let condition = (state.enemy_spirit_share - spirit_mean) * CONDITION_SCALE;
            let mut row = build_feature_row(state, catalog);
            row.features.push((COVARIATES + items, condition));
            for (offset, group) in groups.iter().enumerate() {
                let owned = state
                    .item_ids
                    .iter()
                    .filter(|item| group.contains(item))
                    .count();
                if owned > 0 {
                    row.features.push((
                        COVARIATES + items + 1 + offset,
                        condition * count_as_f64(u64::try_from(owned)?)?,
                    ));
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
    (0..groups.len())
        .map(|offset| {
            let index = COVARIATES + items + 1 + offset;
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
///
/// # Errors
/// Returns an error when a model cannot be fitted.
pub fn estimate_counter_evidence(
    states: &[&LandmarkState],
    catalog: &ItemCatalog,
    groups: &CounterGroups,
) -> Result<Vec<CounterEvidence>> {
    let mut evidence = measure_counter_groups(states, catalog, groups)?;
    evidence.retain(CounterEvidence::is_supported);
    Ok(evidence)
}

/// Measures each counter group at each counter phase, in the direction of its damage type.
///
/// The weapon group coefficient changes sign, because a low spirit share means more weapon damage.
///
/// # Errors
/// Returns an error when a model cannot be fitted.
pub fn measure_counter_groups(
    states: &[&LandmarkState],
    catalog: &ItemCatalog,
    groups: &CounterGroups,
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
        .map(|(damage_type, _)| CounterEvidence {
            damage_type: *damage_type,
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
        let interactions =
            fit_group_interactions(&phase_states, catalog, &item_groups, spirit_mean)?;
        for (group, interaction) in evidence.iter_mut().zip(interactions) {
            let direction = match group.damage_type {
                DamageType::Spirit => 1.0,
                DamageType::Weapon => -1.0,
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
        .filter(|(damage_type, _)| {
            evidence
                .iter()
                .any(|group| group.damage_type == *damage_type)
        })
        .filter_map(|(damage_type, items)| {
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
                damage_type: *damage_type,
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
