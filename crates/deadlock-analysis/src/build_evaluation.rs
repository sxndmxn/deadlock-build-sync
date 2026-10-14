use std::collections::BTreeSet;

use deadlock_data::Result;
use deadlock_guides::{BuildEvaluation, Confidence, HeroEstimate};

use crate::build_assembly::PhaseSets;
use crate::item_effects::{ItemCatalog, LandmarkState, relative_net_worth, standardized_rank};
use crate::ridge_logistic::{FeatureRow, fit_ridge_logistic};

/// Test landmarks. Each one compares owned items with the latest phase set at or before it.
pub const EVALUATION_LANDMARKS: [u32; 5] = [540, 900, 1200, 1500, 1800];
const AGREEMENT_COLUMN: usize = 4;
const WIDTH: usize = 5 + EVALUATION_LANDMARKS.len() - 1;
const MINIMUM_OBSERVATIONS: usize = 200;
const PENALTY: f64 = 1.0;

/// Tests a build on held-out states of one hero.
///
/// Agreement is the cost share of the phase set that the player owns.
/// The model adjusts for relative net worth, team lead, rank, and landmark.
/// The agreement coefficient is the log-odds change from no agreement to full agreement.
///
/// # Errors
/// Returns an error when the model cannot be fitted.
pub fn evaluate_build(
    states: &[&LandmarkState],
    phase_sets: &PhaseSets,
    catalog: &ItemCatalog,
) -> Result<BuildEvaluation> {
    let rows = states
        .iter()
        .filter_map(|state| build_evaluation_row(state, phase_sets, catalog))
        .collect::<Vec<_>>();
    fit_agreement(&rows)
}

/// Tests several builds with one model, for example one build per hero.
///
/// Each state uses the phase sets of its own build.
///
/// # Errors
/// Returns an error when the model cannot be fitted.
pub fn evaluate_pooled_builds(
    builds: &[(Vec<&LandmarkState>, PhaseSets)],
    catalog: &ItemCatalog,
) -> Result<BuildEvaluation> {
    let rows = builds
        .iter()
        .flat_map(|(states, phase_sets)| {
            states
                .iter()
                .filter_map(|state| build_evaluation_row(state, phase_sets, catalog))
        })
        .collect::<Vec<_>>();
    fit_agreement(&rows)
}

fn fit_agreement(rows: &[FeatureRow]) -> Result<BuildEvaluation> {
    if rows.len() < MINIMUM_OBSERVATIONS {
        return Ok(BuildEvaluation {
            agreement_coefficient: 0.0,
            standard_error: 0.0,
            observations: u64::try_from(rows.len())?,
            confidence: Confidence::Limited,
            hero_estimate: None,
        });
    }
    let references = rows.iter().collect::<Vec<_>>();
    let fit = fit_ridge_logistic(&references, &[0.0; WIDTH], &[PENALTY; WIDTH])?;
    let coefficient = fit.coefficients[AGREEMENT_COLUMN];
    let standard_error = fit.standard_error(AGREEMENT_COLUMN)?;
    Ok(BuildEvaluation {
        agreement_coefficient: coefficient,
        standard_error,
        observations: u64::try_from(rows.len())?,
        confidence: Confidence::classify(coefficient, standard_error),
        hero_estimate: None,
    })
}

/// Returns the cost share of the build's latest phase set that the player owns at the state.
///
/// The value is missing outside the test landmarks or before the first phase set.
#[must_use]
pub fn measure_agreement(
    state: &LandmarkState,
    phase_sets: &PhaseSets,
    catalog: &ItemCatalog,
) -> Option<f64> {
    if !EVALUATION_LANDMARKS.contains(&state.landmark_s) {
        return None;
    }
    let (_, target) = phase_sets.range(..=state.landmark_s).next_back()?;
    let target_cost = catalog.cost(target);
    if target_cost == 0 {
        return None;
    }
    let owned = state.item_ids.iter().copied().collect::<BTreeSet<_>>();
    Some(
        f64::from(catalog.cost(&target.intersection(&owned).copied().collect()))
            / f64::from(target_cost),
    )
}

fn build_evaluation_row(
    state: &LandmarkState,
    phase_sets: &PhaseSets,
    catalog: &ItemCatalog,
) -> Option<FeatureRow> {
    let position = EVALUATION_LANDMARKS
        .iter()
        .position(|landmark| *landmark == state.landmark_s)?;
    let agreement = measure_agreement(state, phase_sets, catalog)?;
    let mut features = vec![
        (0, 1.0),
        (1, relative_net_worth(state.net_worth, state.landmark_s)),
        (2, state.team_lead),
        (3, standardized_rank(state.average_badge)),
        (AGREEMENT_COLUMN, agreement),
    ];
    if position > 0 {
        features.push((AGREEMENT_COLUMN + position, 1.0));
    }
    Some(FeatureRow {
        features,
        label: if state.won { 1.0 } else { 0.0 },
    })
}

/// Pulls the held-out coefficient of each tested build toward the mean of comparable builds.
///
/// Split-half tests showed that the differences between heroes are mostly noise (E17 in
/// `docs/research-log.md`). The pull depends on the variance between builds beyond the noise:
/// a build keeps more of its own result when that variance is large or its own error is small.
/// Untested builds and pools with fewer than three tested builds do not change.
pub fn shrink_evaluations(evaluations: &mut [&mut BuildEvaluation]) {
    let tested = evaluations
        .iter()
        .filter(|evaluation| evaluation.standard_error > 0.0)
        .map(|evaluation| (evaluation.agreement_coefficient, evaluation.standard_error))
        .collect::<Vec<_>>();
    if tested.len() < 3 {
        return;
    }
    let count = f64::from(u32::try_from(tested.len()).unwrap_or(u32::MAX));
    let weight_sum = tested.iter().map(|(_, error)| error.powi(-2)).sum::<f64>();
    let pooled = tested
        .iter()
        .map(|(coefficient, error)| coefficient * error.powi(-2))
        .sum::<f64>()
        / weight_sum;
    let mean = tested
        .iter()
        .map(|(coefficient, _)| coefficient)
        .sum::<f64>()
        / count;
    let spread = tested
        .iter()
        .map(|(coefficient, _)| (coefficient - mean).powi(2))
        .sum::<f64>()
        / (count - 1.0);
    let noise = tested.iter().map(|(_, error)| error.powi(2)).sum::<f64>() / count;
    let between = (spread - noise).max(0.0);
    for evaluation in evaluations
        .iter_mut()
        .filter(|evaluation| evaluation.standard_error > 0.0)
    {
        let error = evaluation.standard_error;
        let pull = error.powi(2) / error.mul_add(error, between);
        let coefficient = (evaluation.agreement_coefficient - pooled).mul_add(1.0 - pull, pooled);
        let standard_error = (between * pull + pull.powi(2) / weight_sum).sqrt();
        evaluation.hero_estimate = Some(HeroEstimate {
            agreement_coefficient: evaluation.agreement_coefficient,
            standard_error: error,
        });
        evaluation.agreement_coefficient = coefficient;
        evaluation.standard_error = standard_error;
        evaluation.confidence = Confidence::classify(coefficient, standard_error);
    }
}
