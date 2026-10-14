use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Error, Result, count_as_f64};
use serde::Deserialize;

use crate::ridge_logistic::{FeatureRow, fit_ridge_logistic};

/// Covariates before the item columns: intercept, relative net worth, team lead, and rank.
pub const COVARIATES: usize = 4;
/// Held-out log loss selected these penalties on three patches. See `docs/research-log.md` (E2).
const GLOBAL_ITEM_PENALTY: f64 = 200.0;
const GLOBAL_COVARIATE_PENALTY: f64 = 1e-4;
const HERO_ITEM_PENALTY: f64 = 300.0;
const HERO_COVARIATE_PENALTY: f64 = 1.0;
const MINIMUM_HERO_ROWS: usize = 100;

/// One player at one landmark time, with the items that the player owns.
#[derive(Clone, Debug, Deserialize)]
pub struct LandmarkState {
    pub match_id: u64,
    pub player_slot: u32,
    pub team_id: i32,
    pub hero_id: u64,
    pub fold: String,
    pub landmark_s: u32,
    pub won: bool,
    pub average_badge: u32,
    pub net_worth: u32,
    pub team_lead: f64,
    pub item_ids: Vec<u64>,
    /// The mean share of item spend on spirit items for the enemy heroes in all matches of the run.
    pub enemy_spirit_share: f64,
}

/// The fold of the held-out test matches.
const TEST_FOLD: &str = "test";

impl LandmarkState {
    /// Returns true when the state belongs to the held-out test fold.
    #[must_use]
    pub fn is_test(&self) -> bool {
        self.fold == TEST_FOLD
    }
}

#[derive(Clone, Debug, Deserialize)]
pub struct ItemAsset {
    pub item_id: u64,
    pub item_name: String,
    pub class_name: String,
    pub tier: u8,
    pub cost: u32,
    pub component_items_json: String,
}

/// Shop items in a fixed column order, with the components of each upgrade.
#[derive(Debug)]
pub struct ItemCatalog {
    pub items: Vec<ItemAsset>,
    pub components: BTreeMap<u64, Vec<u64>>,
    columns: BTreeMap<u64, usize>,
}

impl ItemCatalog {
    /// # Errors
    /// Returns an error when an item lists malformed components.
    pub fn new(items: Vec<ItemAsset>) -> Result<Self> {
        let by_class = items
            .iter()
            .map(|item| (item.class_name.as_str(), item.item_id))
            .collect::<BTreeMap<_, _>>();
        let mut components = BTreeMap::new();
        for item in &items {
            let names: Vec<String> = serde_json::from_str(&item.component_items_json)?;
            components.insert(
                item.item_id,
                names
                    .iter()
                    .filter_map(|name| by_class.get(name.as_str()).copied())
                    .collect(),
            );
        }
        let columns = items
            .iter()
            .enumerate()
            .map(|(index, item)| (item.item_id, index))
            .collect();
        Ok(Self {
            items,
            components,
            columns,
        })
    }

    #[must_use]
    pub fn column(&self, item_id: u64) -> Option<usize> {
        self.columns.get(&item_id).copied()
    }

    #[must_use]
    pub fn asset(&self, item_id: u64) -> Option<&ItemAsset> {
        self.column(item_id).map(|index| &self.items[index])
    }

    #[must_use]
    pub fn cost(&self, items: &BTreeSet<u64>) -> u32 {
        items
            .iter()
            .filter_map(|item| self.asset(*item))
            .map(|asset| asset.cost)
            .sum()
    }
}

/// Item effects, adoption, and typical item spend for one hero at one landmark.
#[derive(Clone, Debug)]
pub struct HeroLandmarkEffects {
    pub effects: Vec<f64>,
    pub adoption: Vec<f64>,
    pub owner_win_rates: Vec<f64>,
    pub median_spend: u32,
    pub observations: usize,
}

pub type EffectTable = BTreeMap<(u64, u32), HeroLandmarkEffects>;

/// The effect table key for the values of all heroes together. Hero IDs start at 1.
pub const ALL_HEROES: u64 = 0;

/// Converts a landmark state to model features.
///
/// Relative net worth is the logarithm of net worth divided by 20 souls per second.
#[must_use]
pub fn build_feature_row(state: &LandmarkState, catalog: &ItemCatalog) -> FeatureRow {
    let mut features = vec![
        (0, 1.0),
        (1, relative_net_worth(state.net_worth, state.landmark_s)),
        (2, state.team_lead),
        (3, standardized_rank(state.average_badge)),
    ];
    features.extend(
        state
            .item_ids
            .iter()
            .filter_map(|item| catalog.column(*item))
            .map(|column| (COVARIATES + column, 1.0)),
    );
    FeatureRow {
        features,
        label: if state.won { 1.0 } else { 0.0 },
    }
}

#[must_use]
pub fn relative_net_worth(net_worth: u32, landmark_s: u32) -> f64 {
    f64::from(net_worth.max(1)).ln() - (f64::from(landmark_s.max(1)) * 20.0).ln()
}

/// Converts an average match badge to a rank covariate: 0 at badge 80, and 1 for each 20 badges.
#[must_use]
pub fn standardized_rank(average_badge: u32) -> f64 {
    (f64::from(average_badge) - 80.0) / 20.0
}

/// Ridge penalties on item coefficients. A larger penalty pulls harder toward the prior.
///
/// The global model pulls toward zero. Each hero model pulls toward the global model.
#[derive(Clone, Copy, Debug)]
pub struct EffectPenalties {
    pub global_item: f64,
    pub hero_item: f64,
}

/// The ridge penalties of installed builds.
pub const DEFAULT_PENALTIES: EffectPenalties = EffectPenalties {
    global_item: GLOBAL_ITEM_PENALTY,
    hero_item: HERO_ITEM_PENALTY,
};

/// All coefficients of the global model and each hero model at one landmark.
#[derive(Debug)]
pub struct LandmarkModels {
    pub global: Vec<f64>,
    pub heroes: BTreeMap<u64, Vec<f64>>,
}

/// Fits the global model and each hero model with sufficient rows.
///
/// # Errors
/// Returns an error when a model cannot be fitted.
pub fn fit_landmark_models(
    rows: &[(u64, FeatureRow)],
    width: usize,
    penalties: EffectPenalties,
) -> Result<LandmarkModels> {
    let all_rows = rows.iter().map(|(_, row)| row).collect::<Vec<_>>();
    let global = fit_ridge_logistic(
        &all_rows,
        &vec![0.0; width],
        &build_penalty(width, GLOBAL_COVARIATE_PENALTY, penalties.global_item),
    )?
    .coefficients;
    let mut heroes = BTreeMap::new();
    let hero_ids = rows.iter().map(|(hero, _)| *hero).collect::<BTreeSet<_>>();
    for hero in hero_ids {
        let hero_rows = rows
            .iter()
            .filter(|(owner, _)| *owner == hero)
            .map(|(_, row)| row)
            .collect::<Vec<_>>();
        if hero_rows.len() < MINIMUM_HERO_ROWS {
            continue;
        }
        let fit = fit_ridge_logistic(
            &hero_rows,
            &global,
            &build_penalty(width, HERO_COVARIATE_PENALTY, penalties.hero_item),
        )?;
        heroes.insert(hero, fit.coefficients);
    }
    Ok(LandmarkModels { global, heroes })
}

/// Estimates item effects for each hero and landmark.
///
/// A global model for all heroes gives the prior. Each hero model pulls its item
/// coefficients toward the global values, so heroes with few matches inherit the
/// global estimate and heroes with many matches use their own data.
///
/// # Errors
/// Returns an error when a model cannot be fitted.
pub fn estimate_item_effects(
    states: &[&LandmarkState],
    catalog: &ItemCatalog,
    landmarks: &[u32],
) -> Result<EffectTable> {
    estimate_item_effects_with_penalties(states, catalog, landmarks, DEFAULT_PENALTIES)
}

/// Estimates item effects with specified ridge penalties.
///
/// # Errors
/// Returns an error when a model cannot be fitted.
pub fn estimate_item_effects_with_penalties(
    states: &[&LandmarkState],
    catalog: &ItemCatalog,
    landmarks: &[u32],
    penalties: EffectPenalties,
) -> Result<EffectTable> {
    let width = COVARIATES + catalog.items.len();
    let mut table = EffectTable::new();
    for landmark in landmarks {
        let selected = select_feature_rows(states, catalog, *landmark);
        if selected.is_empty() {
            continue;
        }
        let models = fit_landmark_models(&selected, width, penalties)?;
        let all_rows = selected.iter().map(|(_, row)| row).collect::<Vec<_>>();
        table.insert(
            (ALL_HEROES, *landmark),
            summarize_hero(&all_rows, &models.global, catalog)?,
        );
        for (hero, coefficients) in &models.heroes {
            let rows = selected
                .iter()
                .filter(|(owner, _)| owner == hero)
                .map(|(_, row)| row)
                .collect::<Vec<_>>();
            table.insert(
                (*hero, *landmark),
                summarize_hero(&rows, coefficients, catalog)?,
            );
        }
    }
    Ok(table)
}

/// Returns the hero and feature row of each state at one landmark.
#[must_use]
pub fn select_feature_rows(
    states: &[&LandmarkState],
    catalog: &ItemCatalog,
    landmark: u32,
) -> Vec<(u64, FeatureRow)> {
    states
        .iter()
        .filter(|state| state.landmark_s == landmark)
        .map(|state| (state.hero_id, build_feature_row(state, catalog)))
        .collect()
}

fn build_penalty(width: usize, covariate: f64, item: f64) -> Vec<f64> {
    (0..width)
        .map(|index| if index < COVARIATES { covariate } else { item })
        .collect()
}

fn summarize_hero(
    rows: &[&FeatureRow],
    coefficients: &[f64],
    catalog: &ItemCatalog,
) -> Result<HeroLandmarkEffects> {
    let count = catalog.items.len();
    let mut owners = vec![0_usize; count];
    let mut winners = vec![0_usize; count];
    let mut spends = Vec::with_capacity(rows.len());
    for row in rows {
        let mut spend = 0_u32;
        for (index, _) in row
            .features
            .iter()
            .filter(|(index, _)| *index >= COVARIATES)
        {
            owners[index - COVARIATES] += 1;
            if row.label > 0.5 {
                winners[index - COVARIATES] += 1;
            }
            spend += catalog.items[index - COVARIATES].cost;
        }
        spends.push(spend);
    }
    spends.sort_unstable();
    let median_spend = *spends
        .get(spends.len() / 2)
        .ok_or_else(|| Error::new("Hero landmark has no observations"))?;
    let total = count_as_f64(u64::try_from(rows.len())?)?;
    Ok(HeroLandmarkEffects {
        effects: coefficients[COVARIATES..].to_vec(),
        adoption: owners
            .iter()
            .map(|owners| Ok(count_as_f64(u64::try_from(*owners)?)? / total))
            .collect::<Result<_>>()?,
        owner_win_rates: owners
            .iter()
            .zip(&winners)
            .map(|(owners, winners)| {
                if *owners == 0 {
                    return Ok(0.0);
                }
                Ok(
                    count_as_f64(u64::try_from(*winners)?)?
                        / count_as_f64(u64::try_from(*owners)?)?,
                )
            })
            .collect::<Result<_>>()?,
        median_spend,
        observations: rows.len(),
    })
}
