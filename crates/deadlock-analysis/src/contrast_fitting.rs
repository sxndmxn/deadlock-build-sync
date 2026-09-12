use std::collections::BTreeMap;

use deadlock_data::{Error, Result, count_as_f64};
use ndarray::{Array2, Axis};

use crate::contrast_features::Observations;
use crate::logistic_model::predict_probabilities;

#[derive(Clone, Debug)]
pub struct FittedScores {
    pub observations: Observations,
    pub propensity: Vec<f64>,
    pub treated: Vec<f64>,
    pub control: Vec<f64>,
    pub influence: Vec<f64>,
}

pub fn fit_propensity(observations: &Observations) -> Result<Vec<f64>> {
    cross_fit(observations, &observations.treatment, None).map(|values| {
        values
            .into_iter()
            .map(|value| value.clamp(0.05, 0.95))
            .collect()
    })
}

pub fn fit_outcomes(observations: &Observations, propensity: Vec<f64>) -> Result<FittedScores> {
    let treated = cross_fit(observations, &observations.outcome, Some(true))?;
    let control = cross_fit(observations, &observations.outcome, Some(false))?;
    let influence = (0..observations.matches.len())
        .map(|index| {
            let treatment = observations.treatment[index];
            let outcome = observations.outcome[index];
            let probability = propensity[index];
            ((1.0 - treatment) / (1.0 - probability)).mul_add(
                -(outcome - control[index]),
                (treatment / probability).mul_add(outcome - treated[index], treated[index])
                    - control[index],
            )
        })
        .collect();
    Ok(FittedScores {
        observations: observations.clone(),
        propensity,
        treated,
        control,
        influence,
    })
}

fn cross_fit(
    observations: &Observations,
    labels: &[f64],
    action: Option<bool>,
) -> Result<Vec<f64>> {
    let groups = observations.match_folds()?;
    let mut result = vec![0.0; groups.len()];
    for fold in 0..5 {
        let testing = (0..groups.len())
            .filter(|index| groups[*index] == fold)
            .collect::<Vec<_>>();
        if testing.is_empty() {
            continue;
        }
        let training = (0..groups.len())
            .filter(|index| {
                groups[*index] != fold
                    && action.is_none_or(|action| {
                        matches!(observations.treatment[*index], 1.0) == action
                    })
            })
            .collect::<Vec<_>>();
        let predictions = if training.is_empty() {
            let all = (0..groups.len())
                .filter(|index| groups[*index] != fold)
                .map(|index| labels[index])
                .collect::<Vec<_>>();
            vec![mean(&all)?; testing.len()]
        } else {
            let labels = training
                .iter()
                .map(|index| labels[*index])
                .collect::<Vec<_>>();
            predict_probabilities(
                observations.features.select(Axis(0), &training),
                &labels,
                observations.features.select(Axis(0), &testing),
            )?
        };
        for (index, prediction) in testing.iter().zip(predictions) {
            result[*index] = prediction;
        }
    }
    Ok(result)
}

pub fn maximum_standardized_difference(
    features: &Array2<f64>,
    treatment: &[f64],
    propensity: &[f64],
) -> f64 {
    let weights = treatment
        .iter()
        .zip(propensity)
        .map(|(action, probability)| {
            if matches!(*action, 1.0) {
                1.0 / probability
            } else {
                1.0 / (1.0 - probability)
            }
        })
        .collect::<Vec<_>>();
    let mut maximum = 0.0_f64;
    for column in features.columns() {
        // Center each feature to prevent roundoff differences in constant values.
        let origin = column
            .iter()
            .copied()
            .find(|value| value.is_finite())
            .unwrap_or(0.0);
        let centered = || column.iter().map(|value| value - origin);
        let treated = weighted_statistics(centered(), treatment, &weights, true);
        let control = weighted_statistics(centered(), treatment, &weights, false);
        if let (Some((treated_mean, treated_variance)), Some((control_mean, control_variance))) =
            (treated, control)
        {
            let pooled = treated_variance.midpoint(control_variance).sqrt();
            let difference = (treated_mean - control_mean).abs();
            if pooled > 0.0 {
                maximum = maximum.max(difference / pooled);
            } else if difference != 0.0 {
                return f64::INFINITY;
            }
        }
    }
    maximum
}

fn weighted_statistics(
    values: impl Iterator<Item = f64>,
    treatment: &[f64],
    weights: &[f64],
    action: bool,
) -> Option<(f64, f64)> {
    let selected = values
        .zip(treatment)
        .zip(weights)
        .filter(|((value, treatment), _)| value.is_finite() && matches!(**treatment, 1.0) == action)
        .map(|((value, _), weight)| (value, *weight))
        .collect::<Vec<_>>();
    let total = selected.iter().map(|(_, weight)| weight).sum::<f64>();
    if total <= 0.0 {
        return None;
    }
    let mean = selected
        .iter()
        .map(|(value, weight)| value * weight)
        .sum::<f64>()
        / total;
    let variance = selected
        .iter()
        .map(|(value, weight)| (value - mean).powi(2) * weight)
        .sum::<f64>()
        / total;
    Some((mean, variance))
}

pub fn mean(values: &[f64]) -> Result<f64> {
    if values.is_empty() {
        return Err(Error::new("Mean requires at least one observation"));
    }
    Ok(values.iter().sum::<f64>() / count_as_f64(u64::try_from(values.len())?)?)
}

pub fn cluster_interval(influence: &[f64], matches: &[u64]) -> Result<[f64; 2]> {
    let estimate = mean(influence)?;
    let mut clusters = BTreeMap::<u64, Vec<f64>>::new();
    for (identity, value) in matches.iter().zip(influence) {
        clusters.entry(*identity).or_default().push(*value);
    }
    if clusters.len() < 2 {
        return Ok([estimate, estimate]);
    }
    let values = clusters
        .values()
        .map(|values| mean(values))
        .collect::<Result<Vec<_>>>()?;
    let center = mean(&values)?;
    let count = count_as_f64(u64::try_from(values.len())?)?;
    let variance = values
        .iter()
        .map(|value| (value - center).powi(2))
        .sum::<f64>()
        / (count - 1.0);
    let error = (variance / count).sqrt();
    Ok([
        1.96f64.mul_add(-error, estimate),
        1.96f64.mul_add(error, estimate),
    ])
}
