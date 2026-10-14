use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Error, Result, count_as_f64};
use deadlock_guides::{BuildEvaluation, Confidence, CounterEvidence};

use crate::build_assembly::{ItemScoring, PHASES, assemble_build_with_scoring};
use crate::build_evaluation::{evaluate_build, evaluate_pooled_builds};
use crate::counter_items::{
    CONDITION_SCALE, CounterGroups, fit_group_interactions, mean_enemy_spirit_share,
    measure_counter_groups,
};
use crate::item_effects::{
    COVARIATES, EffectPenalties, EffectTable, ItemCatalog, LandmarkState, build_feature_row,
    estimate_item_effects, fit_landmark_models, standardized_rank,
};
use crate::refresh_configuration::{ExtractionResources, RunPaths};
use crate::ridge_logistic::{FeatureRow, logistic};
use crate::run_inputs::{AssemblyInputs, load_run_inputs};

/// The held-out test result of one item score rule over all heroes.
#[derive(Debug)]
pub struct ScoringResult {
    pub scoring: ItemScoring,
    pub pooled: BuildEvaluation,
    pub heroes: usize,
    pub strong: usize,
    pub moderate: usize,
    pub limited: usize,
    /// The median adoption of CORE items at the phase that added them.
    pub median_core_adoption: f64,
    /// The share of CORE items with an adoption below 3% at the phase that added them.
    pub rare_core_share: f64,
}

/// The adoption below which an item is rare in the scoring comparison.
const RARE_ADOPTION: f64 = 0.03;

/// Compares item score rules on the held-out test fold of one run.
///
/// The item effects come from development matches once. Each rule assembles
/// the build of every hero from these effects. One pooled model then tests all
/// builds of the rule. Each hero test also gives a confidence label.
///
/// # Errors
/// Returns an error when the run, the analysis database, or a model fails.
pub fn compare_item_scoring(
    paths: &RunPaths,
    resources: ExtractionResources,
    rules: &[ItemScoring],
) -> Result<Vec<ScoringResult>> {
    let inputs = load_run_inputs(paths, resources)?;
    let (test, development): (Vec<_>, Vec<_>) =
        inputs.states.iter().partition(|state| state.is_test());
    eprintln!("Estimating item effects from development matches");
    let effects = estimate_item_effects(&development, &inputs.catalog, &PHASES)?;
    let mut test_by_hero = BTreeMap::<u64, Vec<&LandmarkState>>::new();
    for state in test {
        test_by_hero.entry(state.hero_id).or_default().push(state);
    }
    rules
        .iter()
        .map(|scoring| test_item_scoring(*scoring, &test_by_hero, &effects, &inputs))
        .collect()
}

fn test_item_scoring(
    scoring: ItemScoring,
    test_by_hero: &BTreeMap<u64, Vec<&LandmarkState>>,
    effects: &EffectTable,
    inputs: &AssemblyInputs,
) -> Result<ScoringResult> {
    eprintln!("Testing effect scale {}", scoring.effect_scale);
    let mut adoptions = Vec::new();
    let builds = test_by_hero
        .iter()
        .filter_map(|(hero_id, states)| {
            let build = assemble_build_with_scoring(
                *hero_id,
                effects,
                &inputs.catalog,
                &inputs.medians,
                scoring,
            )?;
            adoptions.extend(build.core.iter().map(|item| item.adoption));
            Some((states.clone(), build.phase_sets))
        })
        .collect::<Vec<_>>();
    adoptions.sort_by(f64::total_cmp);
    let rare = adoptions
        .iter()
        .filter(|adoption| **adoption < RARE_ADOPTION)
        .count();
    let mut result = ScoringResult {
        scoring,
        pooled: evaluate_pooled_builds(&builds, &inputs.catalog)?,
        heroes: builds.len(),
        strong: 0,
        moderate: 0,
        limited: 0,
        median_core_adoption: adoptions.get(adoptions.len() / 2).copied().unwrap_or(0.0),
        rare_core_share: count_as_f64(u64::try_from(rare)?)?
            / count_as_f64(u64::try_from(adoptions.len().max(1))?)?,
    };
    for (states, phase_sets) in &builds {
        match evaluate_build(states, phase_sets, &inputs.catalog)?.confidence {
            Confidence::Strong => result.strong += 1,
            Confidence::Moderate => result.moderate += 1,
            Confidence::Limited => result.limited += 1,
        }
    }
    Ok(result)
}

/// One item effect estimate for one hero, phase, and match sample.
#[derive(Debug)]
pub struct ItemEffectRow {
    pub sample: &'static str,
    pub hero_id: u64,
    pub phase_s: u32,
    pub item_id: u64,
    pub item_name: String,
    pub tier: u8,
    pub adoption: f64,
    pub owner_win_rate: f64,
    pub effect: f64,
    pub observations: usize,
}

/// Estimates item effects on two disjoint halves of the development matches.
///
/// Matches with an even identifier form the sample `even`, and the other matches form `odd`.
/// Hero ID 0 identifies the model of all heroes. The test fold is not used.
///
/// # Errors
/// Returns an error when the run, the analysis database, or a model fails.
pub fn estimate_split_item_effects(
    paths: &RunPaths,
    resources: ExtractionResources,
) -> Result<Vec<ItemEffectRow>> {
    let inputs = load_run_inputs(paths, resources)?;
    let (even, odd): (Vec<_>, Vec<_>) = inputs
        .states
        .iter()
        .filter(|state| !state.is_test())
        .partition(|state| state.match_id % 2 == 0);
    let mut rows = Vec::new();
    for (sample, states) in [("even", even), ("odd", odd)] {
        eprintln!("Estimating item effects for sample {sample}");
        let table = estimate_item_effects(&states, &inputs.catalog, &PHASES)?;
        for ((hero_id, phase_s), effects) in &table {
            for (column, item) in inputs.catalog.items.iter().enumerate() {
                rows.push(ItemEffectRow {
                    sample,
                    hero_id: *hero_id,
                    phase_s: *phase_s,
                    item_id: item.item_id,
                    item_name: item.item_name.clone(),
                    tier: item.tier,
                    adoption: effects.adoption[column],
                    owner_win_rate: effects.owner_win_rates[column],
                    effect: effects.effects[column],
                    observations: effects.observations,
                });
            }
        }
    }
    Ok(rows)
}

/// A match condition that can change the effect of each item.
#[derive(Clone, Copy, Debug)]
pub enum Interaction {
    /// The team lead of the player.
    TeamLead,
    /// The enemy spirit share minus its mean in the development matches.
    EnemySpirit,
    /// The standardized rank minus its mean in the development matches.
    Rank,
}

impl Interaction {
    /// The factor that gives the main term of the condition a standard deviation near 1.
    const fn main_scale(self) -> f64 {
        match self {
            Self::TeamLead | Self::EnemySpirit => CONDITION_SCALE,
            Self::Rank => 1.0,
        }
    }
}

/// One design of the item effect model.
///
/// With an interaction, the model has a main term for the condition value.
/// Each item also has a coefficient on the condition value, multiplied by the scale.
/// A larger scale makes the interaction penalty weaker. A scale of 0 keeps only the main term.
#[derive(Clone, Copy, Debug)]
pub struct EffectModel {
    pub penalties: EffectPenalties,
    pub interaction: Option<(Interaction, f64)>,
}

/// The held-out prediction quality of one effect model design.
///
/// The difference compares the log loss with the first design on the same states.
/// Its standard error treats each match as one independent unit.
#[derive(Debug)]
pub struct ModelResult {
    pub model: EffectModel,
    pub log_loss: f64,
    pub difference: f64,
    pub difference_standard_error: f64,
    pub observations: usize,
}

/// Compares effect model designs by the log loss of match result predictions on the test fold.
///
/// The models use development matches at each phase landmark. Each test state uses
/// its hero model, or the global model when the hero has too few development rows.
/// A lower log loss means better predictions.
///
/// # Errors
/// Returns an error when the run, the analysis database, or a model fails.
pub fn compare_effect_models(
    paths: &RunPaths,
    resources: ExtractionResources,
    designs: &[EffectModel],
) -> Result<Vec<ModelResult>> {
    let inputs = load_run_inputs(paths, resources)?;
    let (test, development): (Vec<_>, Vec<_>) =
        inputs.states.iter().partition(|state| state.is_test());
    let count = count_as_f64(u64::try_from(development.len().max(1))?)?;
    let context = ModelContext {
        development: &development,
        test: &test,
        catalog: &inputs.catalog,
        spirit_mean: mean_enemy_spirit_share(&development)?,
        rank_mean: development
            .iter()
            .map(|state| standardized_rank(state.average_badge))
            .sum::<f64>()
            / count,
    };
    let mut reference = None;
    let mut results = Vec::new();
    for model in designs {
        eprintln!("Testing {model:?}");
        let losses = measure_match_losses(&context, *model)?;
        let reference = reference.get_or_insert_with(|| losses.clone());
        results.push(compare_match_losses(*model, &losses, reference)?);
    }
    Ok(results)
}

/// The states, items, and condition mean that all designs of one comparison share.
struct ModelContext<'a> {
    development: &'a [&'a LandmarkState],
    test: &'a [&'a LandmarkState],
    catalog: &'a ItemCatalog,
    spirit_mean: f64,
    rank_mean: f64,
}

/// Builds the feature row of a state, with item interactions when the design has them.
fn build_model_row(
    state: &LandmarkState,
    context: &ModelContext,
    model: EffectModel,
) -> FeatureRow {
    let mut row = build_feature_row(state, context.catalog);
    if let Some((interaction, scale)) = model.interaction {
        let value = match interaction {
            Interaction::TeamLead => state.team_lead,
            Interaction::EnemySpirit => state.enemy_spirit_share - context.spirit_mean,
            Interaction::Rank => standardized_rank(state.average_badge) - context.rank_mean,
        };
        let offset = COVARIATES + context.catalog.items.len();
        row.features.push((
            offset + context.catalog.items.len(),
            value * interaction.main_scale(),
        ));
        row.features.extend(
            state
                .item_ids
                .iter()
                .filter_map(|item| context.catalog.column(*item))
                .map(|column| (offset + column, value * scale)),
        );
    }
    row
}

/// Returns the summed log loss and the state count of each test match.
fn measure_match_losses(
    context: &ModelContext,
    model: EffectModel,
) -> Result<BTreeMap<u64, (f64, usize)>> {
    let catalog = context.catalog;
    let width = if model.interaction.is_some() {
        COVARIATES + 2 * catalog.items.len() + 1
    } else {
        COVARIATES + catalog.items.len()
    };
    let mut losses = BTreeMap::<u64, (f64, usize)>::new();
    for landmark in PHASES {
        let training = context
            .development
            .iter()
            .filter(|state| state.landmark_s == landmark)
            .map(|state| (state.hero_id, build_model_row(state, context, model)))
            .collect::<Vec<_>>();
        let models = fit_landmark_models(&training, width, model.penalties)?;
        for state in context
            .test
            .iter()
            .filter(|state| state.landmark_s == landmark)
        {
            let row = build_model_row(state, context, model);
            let coefficients = models.heroes.get(&state.hero_id).unwrap_or(&models.global);
            let score = row
                .features
                .iter()
                .map(|(index, value)| coefficients[*index] * value)
                .sum::<f64>();
            let probability = logistic(score).clamp(1e-12, 1.0 - 1e-12);
            let entry = losses.entry(state.match_id).or_default();
            entry.0 -= if state.won {
                probability.ln()
            } else {
                (1.0 - probability).ln()
            };
            entry.1 += 1;
        }
    }
    Ok(losses)
}

fn compare_match_losses(
    model: EffectModel,
    losses: &BTreeMap<u64, (f64, usize)>,
    reference: &BTreeMap<u64, (f64, usize)>,
) -> Result<ModelResult> {
    let observations = losses.values().map(|(_, count)| count).sum::<usize>();
    let states = count_as_f64(u64::try_from(observations)?)?;
    let matches = count_as_f64(u64::try_from(losses.len())?)?;
    let differences = losses
        .iter()
        .map(|(match_id, (loss, _))| loss - reference.get(match_id).map_or(0.0, |(base, _)| *base))
        .collect::<Vec<_>>();
    let mean = differences.iter().sum::<f64>() / matches;
    let variance = differences
        .iter()
        .map(|difference| (difference - mean).powi(2))
        .sum::<f64>()
        / (matches - 1.0).max(1.0);
    Ok(ModelResult {
        model,
        log_loss: losses.values().map(|(loss, _)| loss).sum::<f64>() / states,
        difference: differences.iter().sum::<f64>() / states,
        difference_standard_error: (variance * matches).sqrt() / states,
        observations,
    })
}

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
            spirit_mean,
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
                evidence: measure_counter_groups(&states, &inputs.catalog, &groups)?,
            })
        })
        .collect()
}
