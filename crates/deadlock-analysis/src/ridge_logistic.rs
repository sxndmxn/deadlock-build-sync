use deadlock_data::{Error, Result};

const MAXIMUM_ITERATIONS: usize = 30;
const CONVERGENCE_STEP: f64 = 1e-7;

/// One observation with sparse feature values and a binary outcome.
#[derive(Clone, Debug)]
pub struct FeatureRow {
    pub features: Vec<(usize, f64)>,
    pub label: f64,
}

/// Coefficients and the penalized Hessian at the solution.
#[derive(Clone, Debug)]
pub struct RidgeFit {
    pub coefficients: Vec<f64>,
    hessian: Vec<f64>,
}

impl RidgeFit {
    /// Returns the approximate standard error of one coefficient.
    ///
    /// # Errors
    /// Returns an error when the Hessian is not positive definite.
    pub fn standard_error(&self, index: usize) -> Result<f64> {
        let width = self.coefficients.len();
        let mut unit = vec![0.0; width];
        unit[index] = 1.0;
        let solution = solve_cholesky(&self.hessian, width, &unit)?;
        Ok(solution[index].max(0.0).sqrt())
    }
}

/// Fits a logistic regression with the penalty `0.5 * sum(penalty * (b - prior)^2)`.
///
/// The penalty pulls each coefficient toward its prior value. A larger penalty pulls harder.
///
/// # Errors
/// Returns an error for inconsistent dimensions, a feature index outside the width,
/// or a Hessian that is not positive definite.
pub fn fit_ridge_logistic(
    rows: &[&FeatureRow],
    prior: &[f64],
    penalty: &[f64],
) -> Result<RidgeFit> {
    let width = prior.len();
    if penalty.len() != width || penalty.iter().any(|value| *value <= 0.0) {
        return Err(Error::new(
            "Ridge penalty requires one positive value for each coefficient",
        ));
    }
    if rows
        .iter()
        .flat_map(|row| &row.features)
        .any(|(index, _)| *index >= width)
    {
        return Err(Error::new("Feature index exceeds the coefficient count"));
    }
    let mut coefficients = prior.to_vec();
    let mut hessian = vec![0.0; width * width];
    for _ in 0..MAXIMUM_ITERATIONS {
        let gradient = accumulate_derivatives(rows, &coefficients, prior, penalty, &mut hessian);
        let step = solve_cholesky(&hessian, width, &gradient)?;
        let largest = step
            .iter()
            .fold(0.0_f64, |largest, value| largest.max(value.abs()));
        for (coefficient, change) in coefficients.iter_mut().zip(&step) {
            *coefficient -= change;
        }
        if largest < CONVERGENCE_STEP {
            break;
        }
    }
    accumulate_derivatives(rows, &coefficients, prior, penalty, &mut hessian);
    Ok(RidgeFit {
        coefficients,
        hessian,
    })
}

/// Returns the logistic probability for a linear score.
#[must_use]
pub fn logistic(score: f64) -> f64 {
    1.0 / (1.0 + (-score).exp())
}

fn accumulate_derivatives(
    rows: &[&FeatureRow],
    coefficients: &[f64],
    prior: &[f64],
    penalty: &[f64],
    hessian: &mut [f64],
) -> Vec<f64> {
    let width = coefficients.len();
    hessian.fill(0.0);
    let mut gradient = vec![0.0; width];
    for row in rows {
        let score = row
            .features
            .iter()
            .map(|(index, value)| coefficients[*index] * value)
            .sum::<f64>();
        let probability = logistic(score);
        let residual = probability - row.label;
        let weight = probability * (1.0 - probability);
        for (first, first_value) in &row.features {
            gradient[*first] += residual * first_value;
            for (second, second_value) in &row.features {
                hessian[first * width + second] += weight * first_value * second_value;
            }
        }
    }
    for index in 0..width {
        gradient[index] += penalty[index] * (coefficients[index] - prior[index]);
        hessian[index * width + index] += penalty[index];
    }
    gradient
}

fn solve_cholesky(matrix: &[f64], width: usize, right: &[f64]) -> Result<Vec<f64>> {
    let mut lower = vec![0.0; width * width];
    for row in 0..width {
        for column in 0..=row {
            let sum = (0..column)
                .map(|index| lower[row * width + index] * lower[column * width + index])
                .sum::<f64>();
            let value = matrix[row * width + column] - sum;
            if row == column {
                if value <= 0.0 || !value.is_finite() {
                    return Err(Error::new("Ridge Hessian is not positive definite"));
                }
                lower[row * width + column] = value.sqrt();
            } else {
                lower[row * width + column] = value / lower[column * width + column];
            }
        }
    }
    let mut forward = vec![0.0; width];
    for row in 0..width {
        let sum = (0..row)
            .map(|index| lower[row * width + index] * forward[index])
            .sum::<f64>();
        forward[row] = (right[row] - sum) / lower[row * width + row];
    }
    let mut solution = vec![0.0; width];
    for row in (0..width).rev() {
        let sum = (row + 1..width)
            .map(|index| lower[index * width + row] * solution[index])
            .sum::<f64>();
        solution[row] = (forward[row] - sum) / lower[row * width + row];
    }
    Ok(solution)
}
