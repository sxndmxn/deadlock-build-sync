use std::collections::BTreeMap;

use deadlock_data::{Result, read_json};
use deadlock_guides::{BuildEvaluation, Confidence};

use crate::build_assembly::{ItemScoring, PHASES, assemble_build_with_scoring};
use crate::build_evaluation::{evaluate_build, evaluate_pooled_builds};
use crate::hero_build_production::{load_assembly_inputs, open_run_database};
use crate::item_effects::{LandmarkState, estimate_item_effects};
use crate::refresh_configuration::{ExtractionResources, RunPaths, cohort_ranks};

/// The held-out test result of one item score rule over all heroes.
#[derive(Debug)]
pub struct ScoringResult {
    pub scoring: ItemScoring,
    pub pooled: BuildEvaluation,
    pub heroes: usize,
    pub strong: usize,
    pub moderate: usize,
    pub limited: usize,
}

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
    let manifest = read_json(&paths.run.join("manifest.json"))?;
    let ranks = cohort_ranks(&manifest["cohort"])?;
    let (database, parameters) = open_run_database(paths, resources, ranks)?;
    let inputs = load_assembly_inputs(&database, &parameters)?;
    drop(database);
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
        .map(|scoring| {
            eprintln!("Testing effect scale {}", scoring.effect_scale);
            let builds = test_by_hero
                .iter()
                .filter_map(|(hero_id, states)| {
                    assemble_build_with_scoring(
                        *hero_id,
                        &effects,
                        &inputs.catalog,
                        &inputs.medians,
                        *scoring,
                    )
                    .map(|build| (states.clone(), build.phase_sets))
                })
                .collect::<Vec<_>>();
            let mut result = ScoringResult {
                scoring: *scoring,
                pooled: evaluate_pooled_builds(&builds, &inputs.catalog)?,
                heroes: builds.len(),
                strong: 0,
                moderate: 0,
                limited: 0,
            };
            for (states, phase_sets) in &builds {
                match evaluate_build(states, phase_sets, &inputs.catalog)?.confidence {
                    Confidence::Strong => result.strong += 1,
                    Confidence::Moderate => result.moderate += 1,
                    Confidence::Limited => result.limited += 1,
                }
            }
            Ok(result)
        })
        .collect()
}
