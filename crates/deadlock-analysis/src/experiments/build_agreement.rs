use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Result, count_as_f64};
use deadlock_guides::{BuildEvaluation, Confidence};

use crate::build_assembly::{ItemScoring, PHASES, assemble_build, assemble_build_with_scoring};
use crate::build_evaluation::{
    EVALUATION_LANDMARKS, evaluate_build, evaluate_pooled_builds, measure_agreement,
};
use crate::build_variants::select_item_variants;
use crate::counter_items::GroupInteraction;
use crate::item_effects::{
    EffectTable, LandmarkState, estimate_item_effects, relative_net_worth, standardized_rank,
};
use crate::refresh_configuration::{ExtractionResources, RunPaths};
use crate::ridge_logistic::{FeatureRow, fit_ridge_logistic};
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

/// The held-out association of two build agreements with the match result in one model.
#[derive(Debug)]
pub struct AgreementPair {
    pub base: GroupInteraction,
    pub alternative: GroupInteraction,
    pub heroes: usize,
    pub observations: usize,
}

/// Tests whether variant agreement predicts the match result beyond main build agreement.
///
/// The builds come from development matches, as in production. For each test state of a hero
/// with variants, the model uses the main agreement and the largest variant agreement.
///
/// # Errors
/// Returns an error when the run, the analysis database, or a model fails.
pub fn compare_variant_agreement(
    paths: &RunPaths,
    resources: ExtractionResources,
) -> Result<AgreementPair> {
    let inputs = load_run_inputs(paths, resources)?;
    let catalog = &inputs.catalog;
    let (test, development): (Vec<_>, Vec<_>) =
        inputs.states.iter().partition(|state| state.is_test());
    let effects = estimate_item_effects(&development, catalog, &PHASES)?;
    let mut samples = Vec::new();
    let mut heroes = 0;
    let hero_ids = test
        .iter()
        .map(|state| state.hero_id)
        .collect::<BTreeSet<_>>();
    for hero_id in hero_ids {
        let Some(main) = assemble_build(hero_id, &effects, catalog, &inputs.medians) else {
            continue;
        };
        let hero_development = development
            .iter()
            .copied()
            .filter(|state| state.hero_id == hero_id)
            .collect::<Vec<_>>();
        let variants = select_item_variants(
            hero_id,
            &hero_development,
            &effects,
            catalog,
            &inputs.medians,
            &main,
        )?;
        if variants.is_empty() {
            continue;
        }
        heroes += 1;
        for state in test
            .iter()
            .copied()
            .filter(|state| state.hero_id == hero_id)
        {
            let base = measure_agreement(state, &main.phase_sets, catalog);
            let alternative = variants
                .iter()
                .filter_map(|variant| measure_agreement(state, &variant.build.phase_sets, catalog))
                .max_by(f64::total_cmp);
            if let (Some(base), Some(alternative)) = (base, alternative) {
                samples.push((state, base, alternative));
            }
        }
    }
    fit_agreement_pair(&samples, heroes)
}

/// Tests whether agreement with builds of one score rule predicts the match result beyond
/// agreement with builds of another score rule.
///
/// Both builds of each hero come from development matches. The test states are held out.
///
/// # Errors
/// Returns an error when the run, the analysis database, or a model fails.
pub fn compare_scoring_pair(
    paths: &RunPaths,
    resources: ExtractionResources,
    base: ItemScoring,
    alternative: ItemScoring,
) -> Result<AgreementPair> {
    let inputs = load_run_inputs(paths, resources)?;
    let catalog = &inputs.catalog;
    let (test, development): (Vec<_>, Vec<_>) =
        inputs.states.iter().partition(|state| state.is_test());
    let effects = estimate_item_effects(&development, catalog, &PHASES)?;
    let mut samples = Vec::new();
    let mut heroes = 0;
    let hero_ids = test
        .iter()
        .map(|state| state.hero_id)
        .collect::<BTreeSet<_>>();
    for hero_id in hero_ids {
        let assemble = |scoring| {
            assemble_build_with_scoring(hero_id, &effects, catalog, &inputs.medians, scoring)
        };
        let (Some(base_build), Some(alternative_build)) = (assemble(base), assemble(alternative))
        else {
            continue;
        };
        heroes += 1;
        for state in test
            .iter()
            .copied()
            .filter(|state| state.hero_id == hero_id)
        {
            if let (Some(first), Some(second)) = (
                measure_agreement(state, &base_build.phase_sets, catalog),
                measure_agreement(state, &alternative_build.phase_sets, catalog),
            ) {
                samples.push((state, first, second));
            }
        }
    }
    fit_agreement_pair(&samples, heroes)
}

/// Fits one model with two agreements, the covariates, and landmark terms.
fn fit_agreement_pair(
    samples: &[(&LandmarkState, f64, f64)],
    heroes: usize,
) -> Result<AgreementPair> {
    let rows = samples
        .iter()
        .map(|(state, base, alternative)| {
            let mut features = vec![
                (0, 1.0),
                (1, relative_net_worth(state.net_worth, state.landmark_s)),
                (2, state.team_lead),
                (3, standardized_rank(state.average_badge)),
                (4, *base),
                (5, *alternative),
            ];
            if let Some(position) = EVALUATION_LANDMARKS
                .iter()
                .position(|landmark| *landmark == state.landmark_s)
                .filter(|position| *position > 0)
            {
                features.push((5 + position, 1.0));
            }
            FeatureRow {
                features,
                label: if state.won { 1.0 } else { 0.0 },
            }
        })
        .collect::<Vec<_>>();
    let matches = samples
        .iter()
        .map(|(state, _, _)| state.match_id)
        .collect::<Vec<_>>();
    let width = 5 + EVALUATION_LANDMARKS.len();
    let references = rows.iter().collect::<Vec<_>>();
    let fit = fit_ridge_logistic(&references, &vec![0.0; width], &vec![1.0; width])?;
    let interaction = |index| -> Result<GroupInteraction> {
        Ok(GroupInteraction {
            coefficient: fit.coefficients[index],
            standard_error: fit.clustered_standard_error(index, &references, &matches)?,
        })
    };
    Ok(AgreementPair {
        base: interaction(4)?,
        alternative: interaction(5)?,
        heroes,
        observations: rows.len(),
    })
}

/// The held-out test of one hero's main build on two halves of the test matches.
#[derive(Debug)]
pub struct LabelHalves {
    pub hero_id: u64,
    pub even: BuildEvaluation,
    pub odd: BuildEvaluation,
}

/// Tests each hero's main build separately on test matches with even and odd identifiers.
///
/// The build comes from development matches, as in production. Similar results on both halves
/// show that the per-hero confidence label is reliable.
///
/// # Errors
/// Returns an error when the run, the analysis database, or a model fails.
pub fn measure_label_halves(
    paths: &RunPaths,
    resources: ExtractionResources,
) -> Result<Vec<LabelHalves>> {
    let inputs = load_run_inputs(paths, resources)?;
    let catalog = &inputs.catalog;
    let (test, development): (Vec<_>, Vec<_>) =
        inputs.states.iter().partition(|state| state.is_test());
    let effects = estimate_item_effects(&development, catalog, &PHASES)?;
    let hero_ids = test
        .iter()
        .map(|state| state.hero_id)
        .collect::<BTreeSet<_>>();
    let mut results = Vec::new();
    for hero_id in hero_ids {
        let Some(build) = assemble_build(hero_id, &effects, catalog, &inputs.medians) else {
            continue;
        };
        let (even, odd): (Vec<_>, Vec<_>) = test
            .iter()
            .copied()
            .filter(|state| state.hero_id == hero_id)
            .partition(|state| state.match_id % 2 == 0);
        results.push(LabelHalves {
            hero_id,
            even: evaluate_build(&even, &build.phase_sets, catalog)?,
            odd: evaluate_build(&odd, &build.phase_sets, catalog)?,
        });
    }
    Ok(results)
}

/// The pooled held-out test of one score rule at one test landmark.
#[derive(Debug)]
pub struct LandmarkAgreement {
    pub scoring: ItemScoring,
    pub landmark_s: u32,
    pub evaluation: BuildEvaluation,
}

/// Tests the builds of each score rule separately at each test landmark, pooled over heroes.
///
/// # Errors
/// Returns an error when the run, the analysis database, or a model fails.
pub fn compare_scoring_by_landmark(
    paths: &RunPaths,
    resources: ExtractionResources,
    rules: &[ItemScoring],
) -> Result<Vec<LandmarkAgreement>> {
    let inputs = load_run_inputs(paths, resources)?;
    let catalog = &inputs.catalog;
    let (test, development): (Vec<_>, Vec<_>) =
        inputs.states.iter().partition(|state| state.is_test());
    let effects = estimate_item_effects(&development, catalog, &PHASES)?;
    let hero_ids = test
        .iter()
        .map(|state| state.hero_id)
        .collect::<BTreeSet<_>>();
    let mut results = Vec::new();
    for scoring in rules {
        let builds = hero_ids
            .iter()
            .filter_map(|hero_id| {
                assemble_build_with_scoring(*hero_id, &effects, catalog, &inputs.medians, *scoring)
                    .map(|build| (*hero_id, build.phase_sets))
            })
            .collect::<Vec<_>>();
        for landmark_s in EVALUATION_LANDMARKS {
            let groups = builds
                .iter()
                .map(|(hero_id, phase_sets)| {
                    let states = test
                        .iter()
                        .copied()
                        .filter(|state| state.hero_id == *hero_id && state.landmark_s == landmark_s)
                        .collect::<Vec<_>>();
                    (states, phase_sets.clone())
                })
                .collect::<Vec<_>>();
            results.push(LandmarkAgreement {
                scoring: *scoring,
                landmark_s,
                evaluation: evaluate_pooled_builds(&groups, catalog)?,
            });
        }
    }
    Ok(results)
}

/// The pooled held-out test of builds from the earliest part of the development matches.
#[derive(Debug)]
pub struct FractionResult {
    pub fraction: f64,
    pub matches: usize,
    pub evaluation: BuildEvaluation,
}

/// Tests builds that use only the earliest fraction of the development matches.
///
/// Match identifiers increase with time. Each fraction keeps the development matches with the
/// smallest identifiers. All fractions use the same test matches and the installed score rule.
///
/// # Errors
/// Returns an error when a fraction is outside (0, 1], or when the run or a model fails.
pub fn compare_training_fractions(
    paths: &RunPaths,
    resources: ExtractionResources,
    fractions: &[f64],
) -> Result<Vec<FractionResult>> {
    let inputs = load_run_inputs(paths, resources)?;
    let catalog = &inputs.catalog;
    let (test, development): (Vec<_>, Vec<_>) =
        inputs.states.iter().partition(|state| state.is_test());
    let matches = development
        .iter()
        .map(|state| state.match_id)
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect::<Vec<_>>();
    let mut test_by_hero = BTreeMap::<u64, Vec<&LandmarkState>>::new();
    for state in &test {
        test_by_hero.entry(state.hero_id).or_default().push(state);
    }
    let mut results = Vec::new();
    for fraction in fractions {
        if !(*fraction > 0.0 && *fraction <= 1.0) {
            return Err(deadlock_data::Error::new("Each fraction must be in (0, 1]"));
        }
        let target = count_as_f64(u64::try_from(matches.len())?)? * fraction;
        let mut kept = matches.len();
        for count in 1..=matches.len() {
            if count_as_f64(u64::try_from(count)?)? >= target {
                kept = count;
                break;
            }
        }
        let last = matches
            .get(kept.saturating_sub(1))
            .copied()
            .unwrap_or_default();
        let subset = development
            .iter()
            .copied()
            .filter(|state| state.match_id <= last)
            .collect::<Vec<_>>();
        eprintln!("Testing fraction {fraction} with {kept} matches");
        let effects = estimate_item_effects(&subset, catalog, &PHASES)?;
        let builds = test_by_hero
            .iter()
            .filter_map(|(hero_id, states)| {
                assemble_build(*hero_id, &effects, catalog, &inputs.medians)
                    .map(|build| (states.clone(), build.phase_sets))
            })
            .collect::<Vec<_>>();
        results.push(FractionResult {
            fraction: *fraction,
            matches: kept,
            evaluation: evaluate_pooled_builds(&builds, catalog)?,
        });
    }
    Ok(results)
}

/// Tests whether owning the situational items predicts the match result beyond CORE agreement.
///
/// The builds come from development matches. For each test state, the base value is the CORE
/// agreement, and the alternative value is the share of the hero's situational items that the
/// player owns.
///
/// # Errors
/// Returns an error when the run, the analysis database, or a model fails.
pub fn compare_situational_signal(
    paths: &RunPaths,
    resources: ExtractionResources,
) -> Result<AgreementPair> {
    let inputs = load_run_inputs(paths, resources)?;
    let catalog = &inputs.catalog;
    let (test, development): (Vec<_>, Vec<_>) =
        inputs.states.iter().partition(|state| state.is_test());
    let effects = estimate_item_effects(&development, catalog, &PHASES)?;
    let hero_ids = test
        .iter()
        .map(|state| state.hero_id)
        .collect::<BTreeSet<_>>();
    let mut samples = Vec::new();
    let mut heroes = 0;
    for hero_id in hero_ids {
        let Some(build) = assemble_build(hero_id, &effects, catalog, &inputs.medians) else {
            continue;
        };
        let situational = build
            .situational
            .iter()
            .map(|item| item.item_id)
            .collect::<BTreeSet<_>>();
        if situational.is_empty() {
            continue;
        }
        heroes += 1;
        let total = count_as_f64(u64::try_from(situational.len())?)?;
        for state in test
            .iter()
            .copied()
            .filter(|state| state.hero_id == hero_id)
        {
            let Some(core) = measure_agreement(state, &build.phase_sets, catalog) else {
                continue;
            };
            let owned = state
                .item_ids
                .iter()
                .filter(|item| situational.contains(item))
                .count();
            samples.push((state, core, count_as_f64(u64::try_from(owned)?)? / total));
        }
    }
    fit_agreement_pair(&samples, heroes)
}
