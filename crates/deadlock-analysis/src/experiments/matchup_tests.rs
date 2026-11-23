//! Tests whether item groups win less or more against specific enemy heroes (E38).

use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Error, Result, count_as_f64};

use crate::counter_items::{
    COUNTER_PHASES, fit_group_interactions, mean_enemy_spirit_share, spirit_conditions,
};
use crate::item_effects::LandmarkState;
use crate::refresh_configuration::{ExtractionResources, RunPaths};
use crate::ridge_logistic::CoefficientEstimate;
use crate::run_inputs::{TeamHeroes, load_team_heroes};
use crate::run_study::RunStudy;

use super::mix;

/// One enemy hero test: the conditions, the item groups, and the states that it uses.
#[derive(Clone, Debug)]
pub struct EnemyHeroTest {
    /// Each condition is a set of enemy heroes. Its value is the count of these heroes in the
    /// enemy team.
    pub conditions: Vec<BTreeSet<u64>>,
    /// When true, each condition has mean 0 and standard deviation 1 within the phase.
    /// When false, the condition is the count itself, which keeps the rows sparse.
    pub standardize: bool,
    /// The item class names of each group.
    pub groups: Vec<Vec<String>>,
    /// Only the states of this hero. Without a hero, the model has hero terms and uses all heroes.
    pub hero_id: Option<u64>,
    /// Only matches with an even (0) or odd (1) identifier. Without a value, all matches.
    pub match_parity: Option<u64>,
    /// With a seed, the enemy teams move to other teams in a fixed pseudo-random order.
    pub placebo_seed: Option<u64>,
}

/// The interactions of the item groups with the enemy hero conditions at one phase.
#[derive(Debug)]
pub struct EnemyHeroResult {
    pub phase_s: u32,
    /// One row for each condition, with one interaction for each group.
    pub interactions: Vec<Vec<CoefficientEstimate>>,
    pub observations: usize,
}

/// A run loaded for enemy hero tests, with the heroes of each team.
#[derive(Debug)]
pub struct EnemyHeroStudy {
    study: RunStudy,
    teams: TeamHeroes,
}

impl EnemyHeroStudy {
    /// Loads the landmark states and the team heroes of a run.
    ///
    /// # Errors
    /// Returns an error when the run or the analysis database fails.
    pub fn load(paths: &RunPaths, resources: ExtractionResources) -> Result<Self> {
        Ok(Self {
            study: RunStudy::load(paths, resources)?,
            teams: load_team_heroes(paths, resources)?,
        })
    }

    /// Returns the heroes with states in the run.
    #[must_use]
    pub fn hero_ids(&self) -> BTreeSet<u64> {
        self.study.hero_ids()
    }

    /// Fits the counter model of E31 at 20 and 30 minutes with enemy hero conditions.
    ///
    /// The model adjusts for the enemy spirit share, as the enemy item counter test does.
    /// A negative interaction means that the group wins less when more of the condition heroes
    /// are on the enemy team. The standard errors treat each match as one cluster.
    ///
    /// # Errors
    /// Returns an error when an item class name is unknown, or when a model fails.
    pub fn measure(&self, test: &EnemyHeroTest) -> Result<Vec<EnemyHeroResult>> {
        let catalog = self.study.catalog();
        let item_groups = test
            .groups
            .iter()
            .map(|names| {
                names
                    .iter()
                    .map(|name| {
                        catalog
                            .items
                            .iter()
                            .find(|item| item.class_name == *name)
                            .map(|item| item.item_id)
                            .ok_or_else(|| Error::new(format!("Unknown item class name: {name}")))
                    })
                    .collect::<Result<BTreeSet<_>>>()
            })
            .collect::<Result<Vec<_>>>()?;
        let group_references = item_groups.iter().collect::<Vec<_>>();
        let states = self
            .study
            .states()
            .iter()
            .filter(|state| test.hero_id.is_none_or(|hero_id| state.hero_id == hero_id))
            .filter(|state| {
                test.match_parity
                    .is_none_or(|parity| state.match_id % 2 == parity)
            })
            .collect::<Vec<_>>();
        let spirit_mean = mean_enemy_spirit_share(&states)?;
        let mut results = Vec::new();
        for phase_s in COUNTER_PHASES {
            let phase_states = states
                .iter()
                .copied()
                .filter(|state| state.landmark_s == phase_s)
                .collect::<Vec<_>>();
            if phase_states.is_empty() {
                continue;
            }
            let conditions = self.enemy_hero_conditions(&phase_states, test)?;
            let spirit = spirit_conditions(&phase_states, spirit_mean);
            let mut references = conditions.iter().map(Vec::as_slice).collect::<Vec<_>>();
            references.push(&spirit);
            let interactions = fit_group_interactions(
                &phase_states,
                catalog,
                &group_references,
                &references,
                test.hero_id.is_none(),
            )?;
            results.push(EnemyHeroResult {
                phase_s,
                interactions: interactions
                    .chunks(group_references.len().max(1))
                    .take(conditions.len())
                    .map(<[CoefficientEstimate]>::to_vec)
                    .collect(),
                observations: phase_states.len(),
            });
        }
        Ok(results)
    }

    /// Returns one value list for each condition: the count of condition heroes in the enemy team.
    fn enemy_hero_conditions(
        &self,
        states: &[&LandmarkState],
        test: &EnemyHeroTest,
    ) -> Result<Vec<Vec<f64>>> {
        let keys = states
            .iter()
            .map(|state| (state.match_id, state.team_id))
            .collect::<BTreeSet<_>>();
        // The enemy team of a key, or another team in the placebo order.
        let mut sources = keys.iter().copied().collect::<Vec<_>>();
        if let Some(seed) = test.placebo_seed {
            sources.sort_by_key(|(match_id, team_id)| {
                mix(seed ^ match_id ^ (u64::from(team_id.unsigned_abs()) << 40))
            });
        }
        let enemies = keys
            .iter()
            .zip(&sources)
            .map(|(key, (match_id, team_id))| {
                let enemy = self
                    .teams
                    .get(&(*match_id, 1 - *team_id))
                    .ok_or_else(|| Error::new(format!("Match {match_id} has no enemy team")))?;
                Ok((*key, enemy))
            })
            .collect::<Result<BTreeMap<_, _>>>()?;
        test.conditions
            .iter()
            .map(|heroes| {
                let values = states
                    .iter()
                    .map(|state| {
                        let enemy = enemies[&(state.match_id, state.team_id)];
                        count_as_f64(u64::try_from(
                            enemy.iter().filter(|hero| heroes.contains(hero)).count(),
                        )?)
                    })
                    .collect::<Result<Vec<_>>>()?;
                Ok(if test.standardize {
                    standardize(&values)?
                } else {
                    values
                })
            })
            .collect()
    }
}

/// Returns the values with mean 0 and standard deviation 1.
fn standardize(values: &[f64]) -> Result<Vec<f64>> {
    let count = count_as_f64(u64::try_from(values.len().max(1))?)?;
    let mean = values.iter().sum::<f64>() / count;
    let deviation = (values
        .iter()
        .map(|value| (value - mean).powi(2))
        .sum::<f64>()
        / count)
        .sqrt()
        .max(1e-9);
    Ok(values
        .iter()
        .map(|value| (value - mean) / deviation)
        .collect())
}
