use std::collections::BTreeMap;

use deadlock_data::{Result, count_as_f64, read_json};
use deadlock_guides::{BuildEvaluation, Confidence};

use crate::build_assembly::{ItemScoring, PHASES, assemble_build_with_scoring};
use crate::build_evaluation::{evaluate_build, evaluate_pooled_builds};
use crate::hero_build_production::{AssemblyInputs, load_assembly_inputs, open_run_database};
use crate::item_effects::{
    COVARIATES, EffectPenalties, EffectTable, ItemCatalog, LandmarkState, build_feature_row,
    estimate_item_effects, fit_landmark_models, select_feature_rows,
};
use crate::refresh_configuration::{ExtractionResources, RunPaths, cohort_ranks};
use crate::ridge_logistic::logistic;

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
        inputs.states.iter().partition(|state| state.fold == "test");
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
        .filter(|state| state.fold != "test")
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

fn load_run_inputs(paths: &RunPaths, resources: ExtractionResources) -> Result<AssemblyInputs> {
    let manifest = read_json(&paths.run.join("manifest.json"))?;
    let ranks = cohort_ranks(&manifest["cohort"])?;
    let (database, parameters) = open_run_database(paths, resources, ranks)?;
    load_assembly_inputs(&database, &parameters)
}

/// The held-out prediction quality of one pair of ridge penalties.
///
/// The difference compares the log loss with the first pair of the grid on the same states.
/// Its standard error treats each match as one independent unit.
#[derive(Debug)]
pub struct PenaltyResult {
    pub penalties: EffectPenalties,
    pub log_loss: f64,
    pub difference: f64,
    pub difference_standard_error: f64,
    pub observations: usize,
}

/// Compares ridge penalties by the log loss of match result predictions on the test fold.
///
/// The models use development matches at each phase landmark. Each test state uses
/// its hero model, or the global model when the hero has too few development rows.
/// A lower log loss means better predictions.
///
/// # Errors
/// Returns an error when the run, the analysis database, or a model fails.
pub fn compare_effect_penalties(
    paths: &RunPaths,
    resources: ExtractionResources,
    grid: &[EffectPenalties],
) -> Result<Vec<PenaltyResult>> {
    let inputs = load_run_inputs(paths, resources)?;
    let (test, development): (Vec<_>, Vec<_>) =
        inputs.states.iter().partition(|state| state.fold == "test");
    let mut reference = None;
    let mut results = Vec::new();
    for penalties in grid {
        eprintln!(
            "Testing penalties {} and {}",
            penalties.global_item, penalties.hero_item
        );
        let losses = measure_match_losses(&development, &test, &inputs.catalog, *penalties)?;
        let reference = reference.get_or_insert_with(|| losses.clone());
        results.push(compare_match_losses(*penalties, &losses, reference)?);
    }
    Ok(results)
}

/// Returns the summed log loss and the state count of each test match.
fn measure_match_losses(
    development: &[&LandmarkState],
    test: &[&LandmarkState],
    catalog: &ItemCatalog,
    penalties: EffectPenalties,
) -> Result<BTreeMap<u64, (f64, usize)>> {
    let width = COVARIATES + catalog.items.len();
    let mut losses = BTreeMap::<u64, (f64, usize)>::new();
    for landmark in PHASES {
        let training = select_feature_rows(development, catalog, landmark);
        let models = fit_landmark_models(&training, width, penalties)?;
        for state in test.iter().filter(|state| state.landmark_s == landmark) {
            let row = build_feature_row(state, catalog);
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
    penalties: EffectPenalties,
    losses: &BTreeMap<u64, (f64, usize)>,
    reference: &BTreeMap<u64, (f64, usize)>,
) -> Result<PenaltyResult> {
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
    Ok(PenaltyResult {
        penalties,
        log_loss: losses.values().map(|(loss, _)| loss).sum::<f64>() / states,
        difference: differences.iter().sum::<f64>() / states,
        difference_standard_error: (variance * matches).sqrt() / states,
        observations,
    })
}
