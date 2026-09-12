use basin::{
    BoxConstraints, CostFunction, Executor, Gradient, LbfgsState, Lbfgsb, MoreThuente, State,
    TerminationReason,
};
use deadlock_data::{Error, Result, count_as_f64};
use ndarray::{Array2, ArrayView1};

use crate::statistics::quantiles;

#[derive(Debug)]
struct LogisticProblem {
    rows: Vec<f64>,
    width: usize,
    labels: Vec<f64>,
    population: f64,
    lower: Vec<f64>,
    upper: Vec<f64>,
}

impl LogisticProblem {
    fn evaluate<const DERIVATIVE: bool>(&self, parameters: &[f64]) -> Result<(f64, Vec<f64>)> {
        let mut cost = 0.0;
        let mut gradient = if DERIVATIVE {
            vec![0.0; parameters.len()]
        } else {
            Vec::new()
        };
        let coefficients = ArrayView1::from(&parameters[..self.width]);
        for (row, label) in self.rows.chunks_exact(self.width).zip(&self.labels) {
            let score = ArrayView1::from(row).dot(&coefficients) + parameters[self.width];
            let (loss, probability) = logistic_terms(score, *label);
            cost += loss;
            if DERIVATIVE {
                let residual = probability - label;
                for (entry, feature) in gradient.iter_mut().zip(row) {
                    *entry += residual * feature;
                }
                gradient[self.width] += residual;
            }
        }
        let penalty = parameters[..self.width]
            .iter()
            .map(|value| value * value)
            .sum::<f64>();
        cost = (cost + penalty) / self.population;
        for (index, entry) in gradient.iter_mut().enumerate() {
            if index < self.width {
                *entry += 2.0 * parameters[index];
            }
            *entry /= self.population;
        }
        if !cost.is_finite() || gradient.iter().any(|value| !value.is_finite()) {
            return Err(Error::new("Logistic loss or gradient is not finite"));
        }
        Ok((cost, gradient))
    }
}

impl CostFunction for LogisticProblem {
    type Param = Vec<f64>;
    type Output = f64;
    type Error = Error;

    fn cost(&self, parameters: &Vec<f64>) -> Result<f64> {
        self.evaluate::<false>(parameters).map(|(cost, _)| cost)
    }
}

impl Gradient for LogisticProblem {
    type Gradient = Vec<f64>;

    fn gradient(&self, parameters: &Vec<f64>) -> Result<Vec<f64>> {
        self.evaluate::<true>(parameters)
            .map(|(_, gradient)| gradient)
    }

    fn cost_and_gradient(&self, parameters: &Vec<f64>) -> Result<(f64, Vec<f64>)> {
        self.evaluate::<true>(parameters)
    }
}

fn logistic_terms(score: f64, label: f64) -> (f64, f64) {
    if score >= 0.0 {
        let exponential = (-score).exp();
        (
            (1.0 - label).mul_add(score, exponential.ln_1p()),
            1.0 / (1.0 + exponential),
        )
    } else {
        let exponential = score.exp();
        (
            (-label).mul_add(score, exponential.ln_1p()),
            exponential / (1.0 + exponential),
        )
    }
}

impl BoxConstraints for LogisticProblem {
    fn lower(&self) -> &Vec<f64> {
        &self.lower
    }
    fn upper(&self) -> &Vec<f64> {
        &self.upper
    }
}

pub fn predict_probabilities(
    training: Array2<f64>,
    labels: &[f64],
    prediction: Array2<f64>,
) -> Result<Vec<f64>> {
    let invalid_labels =
        training.nrows() != labels.len() || labels.iter().any(|label| !matches!(*label, 0.0 | 1.0));
    if invalid_labels || training.ncols() != prediction.ncols() {
        return Err(Error::new("Logistic features or labels are invalid"));
    }
    let population = count_as_f64(u64::try_from(labels.len())?)?;
    if labels.iter().all(|label| Some(label) == labels.first()) {
        return Ok(vec![
            (labels.iter().sum::<f64>() + 1.0) / (population + 2.0);
            prediction.nrows()
        ]);
    }
    let (training, prediction) = standardize(training, prediction)?;
    let width = training.ncols();
    let problem = LogisticProblem {
        rows: training.iter().copied().collect(),
        width,
        labels: labels.to_vec(),
        population,
        lower: vec![f64::NEG_INFINITY; width + 1],
        upper: vec![f64::INFINITY; width + 1],
    };
    let solver = Lbfgsb::with_line_search(MoreThuente::new().maxfev(50))
        .with_absolute_projected_gradient_tolerance(1e-4);
    let mut previous = None::<f64>;
    let result = Executor::new(problem, solver, LbfgsState::new(vec![0.0; width + 1], 10))
        .max_iter(500)
        .max_cost_evals(15001)
        .stop_when(move |state| {
            let cost = state.cost();
            let prior = previous.replace(cost)?;
            (prior - cost <= 64.0 * f64::EPSILON * prior.abs().max(cost.abs()).max(1.0))
                .then_some(TerminationReason::UserRequested)
        })
        .run()
        .map_err(|error| Error::new(format!("Logistic optimization failed: {error}")))?;
    if result.iter() >= 500 || result.cost_evals() >= 15001 {
        return Err(Error::new(
            "Logistic optimization did not converge within its fixed limits",
        ));
    }
    let parameters = result.param();
    Ok(prediction
        .rows()
        .into_iter()
        .map(|row| {
            sigmoid(
                row.iter()
                    .zip(parameters)
                    .map(|(feature, coefficient)| feature * coefficient)
                    .sum::<f64>()
                    + parameters[width],
            )
        })
        .collect())
}

fn standardize(
    mut training: Array2<f64>,
    mut prediction: Array2<f64>,
) -> Result<(Array2<f64>, Array2<f64>)> {
    if training.ncols() == 0
        || training.nrows() == 0
        || training
            .iter()
            .chain(&prediction)
            .any(|value| value.is_infinite())
    {
        return Err(Error::new(
            "Logistic features are empty or contain infinity",
        ));
    }
    let population = count_as_f64(u64::try_from(training.nrows())?)?;
    for column in 0..training.ncols() {
        impute_missing(&mut training, &mut prediction, column)?;
        let mean = training.column(column).sum() / population;
        let correction = training
            .column(column)
            .iter()
            .map(|value| value - mean)
            .sum::<f64>();
        let squares = training
            .column(column)
            .iter()
            .map(|value| (value - mean).powi(2))
            .sum::<f64>();
        let variance = ((squares - correction.powi(2) / population) / population).max(0.0);
        let upper = (population * mean * f64::EPSILON).mul_add(
            population * mean * f64::EPSILON,
            population * f64::EPSILON * variance,
        );
        let scale = if variance <= upper {
            1.0
        } else {
            variance.sqrt()
        };
        for value in training
            .column_mut(column)
            .iter_mut()
            .chain(prediction.column_mut(column).iter_mut())
        {
            *value = (*value - mean) / scale;
        }
    }
    Ok((training, prediction))
}

fn impute_missing(
    training: &mut Array2<f64>,
    prediction: &mut Array2<f64>,
    column: usize,
) -> Result<()> {
    if !training
        .column(column)
        .iter()
        .chain(prediction.column(column).iter())
        .any(|value| value.is_nan())
    {
        return Ok(());
    }
    let mut observed = training
        .column(column)
        .iter()
        .copied()
        .filter(|value| !value.is_nan())
        .collect::<Vec<_>>();
    let median = quantiles(&mut observed)?.map_or(0.0, |values| values[1]);
    for value in training
        .column_mut(column)
        .iter_mut()
        .chain(prediction.column_mut(column).iter_mut())
    {
        if value.is_nan() {
            *value = median;
        }
    }
    Ok(())
}

fn sigmoid(value: f64) -> f64 {
    if value >= 0.0 {
        1.0 / (1.0 + (-value).exp())
    } else {
        let exponential = value.exp();
        exponential / (1.0 + exponential)
    }
}
