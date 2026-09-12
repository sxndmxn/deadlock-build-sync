use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Error, Result, count_ratio};
use ndarray::Axis;
use serde::Serialize;
use serde_json::Value;

use crate::contrast_features::Observations;
use crate::contrast_fitting::{
    FittedScores, cluster_interval, fit_outcomes, fit_propensity, maximum_standardized_difference,
    mean,
};

#[derive(Clone, Debug, Serialize)]
pub struct FoldDiagnostics {
    pub support: u64,
    pub comparison_support: u64,
    pub effective_support: f64,
    pub overlap: f64,
    pub maximum_weight: f64,
    pub maximum_standardized_mean_difference: f64,
    pub estimate: f64,
    pub interval: [f64; 2],
}

#[derive(Clone, Debug, Serialize)]
pub struct Contrast {
    pub treatment_item_id: u64,
    pub comparator_item_id: u64,
    #[serde(flatten)]
    pub aggregate: FoldDiagnostics,
    pub fold_estimates: BTreeMap<String, f64>,
    pub fold_diagnostics: BTreeMap<String, FoldDiagnostics>,
    pub clipped_sensitivity: BTreeMap<String, f64>,
    pub stable: bool,
    pub admitted: bool,
    pub failed_gates: Vec<String>,
}

#[derive(Clone, Debug, Serialize)]
pub struct BalanceRejection {
    pub fold: String,
    pub support: u64,
    pub comparison_support: u64,
    pub maximum_standardized_mean_difference: f64,
}

#[derive(Clone, Debug)]
pub enum ContrastResult {
    Rejected(BalanceRejection),
    Estimated(Contrast),
}

pub fn estimate_contrast<'a>(
    rows: impl IntoIterator<Item = &'a Value>,
    treatment: u64,
    comparator: u64,
) -> Result<ContrastResult> {
    let observations = Observations::from_rows(rows, treatment)?;
    let mut scores = Vec::new();
    let mut diagnostics: BTreeMap<String, FoldDiagnostics> = BTreeMap::new();
    for period in ["train", "validation"] {
        let indices = observations
            .periods
            .iter()
            .enumerate()
            .filter(|(_, value)| *value == period)
            .map(|(index, _)| index)
            .collect::<Vec<_>>();
        let subset = observations.select(&indices);
        let count = subset
            .treatment
            .iter()
            .filter(|value| matches!(**value, 1.0))
            .count();
        if subset.matches.len() < 4
            || count == 0
            || count == subset.matches.len()
            || subset.matches.iter().collect::<BTreeSet<_>>().len() < 2
        {
            return Err(Error::new(format!("{period} lacks cross-fitting support")));
        }
        let propensity = fit_propensity(&subset)?;
        let difference =
            maximum_standardized_difference(&subset.features, &subset.treatment, &propensity);
        if difference > 0.10 {
            return Ok(ContrastResult::Rejected(BalanceRejection {
                fold: period.into(),
                support: u64::try_from(count)?,
                comparison_support: u64::try_from(subset.matches.len() - count)?,
                maximum_standardized_mean_difference: difference,
            }));
        }
        let result = fit_outcomes(&subset, propensity)?;
        diagnostics.insert(period.into(), describe_scores(&result)?);
        scores.push(result);
    }
    let scores = merge_scores(&scores)?;
    let aggregate = describe_scores(&scores)?;
    let fold_estimates = diagnostics
        .iter()
        .map(|(name, diagnostics)| (name.clone(), diagnostics.estimate))
        .collect::<BTreeMap<String, f64>>();
    let stable = (fold_estimates["train"] - fold_estimates["validation"]).abs() <= 0.05;
    let failed_gates = failed_gates(&diagnostics, stable);
    Ok(ContrastResult::Estimated(Contrast {
        treatment_item_id: treatment,
        comparator_item_id: comparator,
        aggregate,
        fold_estimates,
        fold_diagnostics: diagnostics,
        clipped_sensitivity: clipped_sensitivity(&scores)?,
        stable,
        admitted: failed_gates.is_empty(),
        failed_gates,
    }))
}

fn describe_scores(scores: &FittedScores) -> Result<FoldDiagnostics> {
    let weights = scores
        .observations
        .treatment
        .iter()
        .zip(&scores.propensity)
        .map(|(action, probability)| {
            if matches!(*action, 1.0) {
                1.0 / probability
            } else {
                1.0 / (1.0 - probability)
            }
        })
        .collect::<Vec<_>>();
    let support = u64::try_from(
        scores
            .observations
            .treatment
            .iter()
            .filter(|value| matches!(**value, 1.0))
            .count(),
    )?;
    let count = u64::try_from(weights.len())?;
    Ok(FoldDiagnostics {
        support,
        comparison_support: count - support,
        effective_support: weights.iter().sum::<f64>().powi(2)
            / weights.iter().map(|weight| weight * weight).sum::<f64>(),
        overlap: count_ratio(
            u64::try_from(
                scores
                    .propensity
                    .iter()
                    .filter(|value| (0.1..=0.9).contains(*value))
                    .count(),
            )?,
            count,
        )?,
        maximum_weight: weights.iter().copied().fold(0.0, f64::max),
        maximum_standardized_mean_difference: maximum_standardized_difference(
            &scores.observations.features,
            &scores.observations.treatment,
            &scores.propensity,
        ),
        estimate: mean(&scores.influence)?,
        interval: cluster_interval(&scores.influence, &scores.observations.matches)?,
    })
}

fn failed_gates(diagnostics: &BTreeMap<String, FoldDiagnostics>, stable: bool) -> Vec<String> {
    let rows = diagnostics.values().collect::<Vec<_>>();
    [
        (
            "support",
            rows.iter()
                .all(|row| row.support.min(row.comparison_support) >= 20),
        ),
        (
            "effective_support",
            rows.iter().all(|row| row.effective_support >= 20.0),
        ),
        ("overlap", rows.iter().all(|row| row.overlap >= 0.5)),
        (
            "balance",
            rows.iter()
                .all(|row| row.maximum_standardized_mean_difference <= 0.1),
        ),
        (
            "bounded_uncertainty",
            rows.iter()
                .all(|row| row.interval[1] - row.interval[0] <= 0.1),
        ),
        (
            "positive_advantage",
            rows.iter().all(|row| row.interval[0] > 0.0),
        ),
        ("temporal_stability", stable),
    ]
    .into_iter()
    .filter(|(_, passed)| !*passed)
    .map(|(name, _)| name.into())
    .collect()
}

fn clipped_sensitivity(scores: &FittedScores) -> Result<BTreeMap<String, f64>> {
    [5.0_f64, 10.0, 20.0]
        .into_iter()
        .map(|clip| {
            let values = (0..scores.propensity.len())
                .map(|index| {
                    let treatment = scores.observations.treatment[index];
                    let outcome = scores.observations.outcome[index];
                    let probability = scores.propensity[index];
                    ((1.0 - treatment) * (1.0 / (1.0 - probability)).min(clip)).mul_add(
                        -(outcome - scores.control[index]),
                        (treatment * (1.0 / probability).min(clip))
                            .mul_add(outcome - scores.treated[index], scores.treated[index])
                            - scores.control[index],
                    )
                })
                .collect::<Vec<_>>();
            Ok((format!("clip={clip}"), mean(&values)?))
        })
        .collect()
}

fn merge_scores(scores: &[FittedScores]) -> Result<FittedScores> {
    let features = ndarray::concatenate(
        Axis(0),
        &scores
            .iter()
            .map(|score| score.observations.features.view())
            .collect::<Vec<_>>(),
    )
    .map_err(|error| Error::new(error.to_string()))?;
    let observations = Observations {
        features,
        treatment: scores
            .iter()
            .flat_map(|score| score.observations.treatment.iter().copied())
            .collect(),
        outcome: scores
            .iter()
            .flat_map(|score| score.observations.outcome.iter().copied())
            .collect(),
        matches: scores
            .iter()
            .flat_map(|score| score.observations.matches.iter().copied())
            .collect(),
        periods: scores
            .iter()
            .flat_map(|score| score.observations.periods.iter().cloned())
            .collect(),
    };
    Ok(FittedScores {
        observations,
        propensity: scores
            .iter()
            .flat_map(|score| score.propensity.iter().copied())
            .collect(),
        treated: scores
            .iter()
            .flat_map(|score| score.treated.iter().copied())
            .collect(),
        control: scores
            .iter()
            .flat_map(|score| score.control.iter().copied())
            .collect(),
        influence: scores
            .iter()
            .flat_map(|score| score.influence.iter().copied())
            .collect(),
    })
}
