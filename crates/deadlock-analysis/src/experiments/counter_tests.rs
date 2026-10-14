use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Error, Result};
use deadlock_guides::CounterEvidence;

use crate::build_assembly::PHASES;
use crate::counter_items::{
    COUNTER_PHASES, CounterGroups, GroupInteraction, enemy_item_conditions, fit_group_interactions,
    mean_enemy_spirit_share, measure_counter_groups, spirit_conditions,
};
use crate::refresh_configuration::{ExtractionResources, RunPaths};
use crate::run_inputs::load_run_inputs;

use super::mix;

/// The interaction of two defensive item groups with the enemy spirit share at one phase.
///
/// Each coefficient is the change in log-odds for each owned item of the group when
/// the enemy spirit share is one standard deviation (about 0.06) above its mean.
#[derive(Debug)]
pub struct CounterResult {
    pub phase_s: u32,
    pub spirit_defense: f64,
    pub spirit_defense_standard_error: f64,
    pub weapon_defense: f64,
    pub weapon_defense_standard_error: f64,
    pub observations: usize,
}

/// Tests whether defensive items win more against the matching enemy damage type.
///
/// The global model of each phase uses all matches. It adds a main term for the enemy
/// spirit share and one interaction term for each item group.
///
/// # Errors
/// Returns an error when an item name is unknown, or when the run or a model fails.
pub fn estimate_counter_interactions(
    paths: &RunPaths,
    resources: ExtractionResources,
    spirit_defense: &[&str],
    weapon_defense: &[&str],
) -> Result<Vec<CounterResult>> {
    let inputs = load_run_inputs(paths, resources)?;
    let catalog = &inputs.catalog;
    let find = |names: &[&str]| {
        names
            .iter()
            .map(|name| {
                catalog
                    .items
                    .iter()
                    .find(|item| item.item_name == *name)
                    .map(|item| item.item_id)
                    .ok_or_else(|| Error::new(format!("Unknown item name: {name}")))
            })
            .collect::<Result<BTreeSet<_>>>()
    };
    let groups = [find(spirit_defense)?, find(weapon_defense)?];
    let states = inputs.states.iter().collect::<Vec<_>>();
    let spirit_mean = mean_enemy_spirit_share(&states)?;
    let mut results = Vec::new();
    for phase_s in PHASES {
        let phase_states = states
            .iter()
            .copied()
            .filter(|state| state.landmark_s == phase_s)
            .collect::<Vec<_>>();
        let interactions = fit_group_interactions(
            &phase_states,
            catalog,
            &[&groups[0], &groups[1]],
            &[&spirit_conditions(&phase_states, spirit_mean)],
            false,
        )?;
        results.push(CounterResult {
            phase_s,
            spirit_defense: interactions[0].coefficient,
            spirit_defense_standard_error: interactions[0].standard_error,
            weapon_defense: interactions[1].coefficient,
            weapon_defense_standard_error: interactions[1].standard_error,
            observations: phase_states.len(),
        });
    }
    Ok(results)
}

/// The counter evidence of one time window of a run.
#[derive(Debug)]
pub struct WindowEvidence {
    pub window: usize,
    pub matches: usize,
    pub evidence: Vec<CounterEvidence>,
}

/// Measures the counter groups in windows with equal match counts, ordered by match identifier.
///
/// Match identifiers increase with time, so each window covers a part of the run period.
///
/// # Errors
/// Returns an error when the window count is zero, or when the run or a model fails.
pub fn measure_counter_windows(
    paths: &RunPaths,
    resources: ExtractionResources,
    windows: usize,
    hero_terms: bool,
) -> Result<Vec<WindowEvidence>> {
    if windows == 0 {
        return Err(Error::new("The window count must be positive"));
    }
    let inputs = load_run_inputs(paths, resources)?;
    let groups = CounterGroups::from_catalog(&inputs.catalog);
    let matches = inputs
        .states
        .iter()
        .map(|state| state.match_id)
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect::<Vec<_>>();
    let size = matches.len().div_ceil(windows);
    matches
        .chunks(size.max(1))
        .enumerate()
        .map(|(window, chunk)| {
            let ids = chunk.iter().copied().collect::<BTreeSet<_>>();
            let states = inputs
                .states
                .iter()
                .filter(|state| ids.contains(&state.match_id))
                .collect::<Vec<_>>();
            eprintln!("Measuring window {window} with {} matches", chunk.len());
            Ok(WindowEvidence {
                window,
                matches: chunk.len(),
                evidence: measure_counter_groups(&states, &inputs.catalog, &groups, hero_terms)?,
            })
        })
        .collect()
}

/// The interactions of item groups with one enemy item condition at one phase.
#[derive(Debug)]
pub struct ConditionResult {
    pub phase_s: u32,
    pub interactions: Vec<GroupInteraction>,
    pub observations: usize,
}

/// Tests whether item groups win more when the enemy team owns more of a set of items.
///
/// The condition of a state is the share of enemy item cost in the condition items at the
/// landmark, standardized within the phase. Items are given by class name.
///
/// # Errors
/// Returns an error when a class name is unknown, or when the run or a model fails.
pub fn estimate_enemy_item_counters(
    paths: &RunPaths,
    resources: ExtractionResources,
    condition_items: &[&str],
    groups: &[Vec<&str>],
    hero_terms: bool,
) -> Result<Vec<ConditionResult>> {
    let inputs = load_run_inputs(paths, resources)?;
    let catalog = &inputs.catalog;
    let find = |names: &[&str]| {
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
    };
    let condition_set = find(condition_items)?;
    let item_groups = groups
        .iter()
        .map(|names| find(names))
        .collect::<Result<Vec<_>>>()?;
    let group_references = item_groups.iter().collect::<Vec<_>>();
    let all_states = inputs.states.iter().collect::<Vec<_>>();
    let spirit_mean = mean_enemy_spirit_share(&all_states)?;
    let mut results = Vec::new();
    for phase_s in PHASES {
        let phase_states = inputs
            .states
            .iter()
            .filter(|state| state.landmark_s == phase_s)
            .collect::<Vec<_>>();
        let conditions = enemy_item_conditions(&phase_states, catalog, &condition_set)?;
        let spirit = spirit_conditions(&phase_states, spirit_mean);
        let mut interactions = fit_group_interactions(
            &phase_states,
            catalog,
            &group_references,
            &[&conditions, &spirit],
            hero_terms,
        )?;
        interactions.truncate(group_references.len());
        results.push(ConditionResult {
            phase_s,
            interactions,
            observations: phase_states.len(),
        });
    }
    Ok(results)
}

/// The z values of one placebo repetition of the counter test.
#[derive(Debug)]
pub struct PlaceboResult {
    pub seed: u64,
    pub phase_s: u32,
    pub z_values: Vec<f64>,
}

/// Repeats the counter test after the team conditions are moved to other teams at random.
///
/// The move removes any real relation between the conditions and the players. Thus, the z values
/// should follow a standard normal distribution when the standard errors are correct.
/// The z values hold the spirit block for each group, then the sustain block for each group.
///
/// # Errors
/// Returns an error when the run, the analysis database, or a model fails.
pub fn measure_counter_placebo(
    paths: &RunPaths,
    resources: ExtractionResources,
    seeds: &[u64],
) -> Result<Vec<PlaceboResult>> {
    let inputs = load_run_inputs(paths, resources)?;
    let catalog = &inputs.catalog;
    let groups = CounterGroups::from_catalog(catalog);
    let item_groups = groups.item_groups();
    let states = inputs.states.iter().collect::<Vec<_>>();
    let spirit_mean = mean_enemy_spirit_share(&states)?;
    let mut results = Vec::new();
    for phase_s in COUNTER_PHASES {
        let phase_states = states
            .iter()
            .copied()
            .filter(|state| state.landmark_s == phase_s)
            .collect::<Vec<_>>();
        let spirit = spirit_conditions(&phase_states, spirit_mean);
        let sustain = enemy_item_conditions(&phase_states, catalog, groups.sustain_items())?;
        let teams = phase_states
            .iter()
            .zip(spirit.iter().zip(&sustain))
            .map(|(state, (spirit, sustain))| {
                ((state.match_id, state.team_id), (*spirit, *sustain))
            })
            .collect::<BTreeMap<_, _>>();
        for seed in seeds {
            let mut keys = teams.keys().copied().collect::<Vec<_>>();
            keys.sort_by_key(|(match_id, team_id)| {
                mix(seed ^ match_id ^ (u64::from(team_id.unsigned_abs()) << 40))
            });
            let moved = teams
                .keys()
                .zip(&keys)
                .map(|(target, source)| (*target, teams[source]))
                .collect::<BTreeMap<_, _>>();
            let (placebo_spirit, placebo_sustain): (Vec<_>, Vec<_>) = phase_states
                .iter()
                .map(|state| moved[&(state.match_id, state.team_id)])
                .unzip();
            let interactions = fit_group_interactions(
                &phase_states,
                catalog,
                &item_groups,
                &[&placebo_spirit, &placebo_sustain],
                false,
            )?;
            results.push(PlaceboResult {
                seed: *seed,
                phase_s,
                z_values: interactions
                    .iter()
                    .map(|interaction| interaction.coefficient / interaction.standard_error)
                    .collect(),
            });
        }
    }
    Ok(results)
}
