use deadlock_data::{Error, Result, array, count_as_f64, normal_quantile, object};
use serde_json::Value;

use crate::evidence_values::{close, finite};

pub fn validate_branch_diagnostics(evidence: &Value, support: u64, lower: f64) -> Result<()> {
    let family = finite(&evidence["hypotheses"], "automatic choice hypothesis count")?;
    let folds = object(&evidence["fold_diagnostics"])?;
    if family < 1.0
        || family.fract().abs() > 0.0
        || folds.len() != 2
        || !folds.contains_key("train")
        || !folds.contains_key("validation")
    {
        return Err(Error::new(
            "Automatic choice has invalid validation folds or family correction",
        ));
    }
    if evidence["admitted"].as_bool() != Some(true)
        || evidence["stable"].as_bool() != Some(true)
        || !array(&evidence["failed_gates"])?.is_empty()
    {
        return Err(Error::new(
            "Automatic choice has failed comparison requirements",
        ));
    }
    let critical = normal_quantile(1.0 - 0.025 / family)?;
    let training = validate_fold(&folds["train"], critical)?;
    let validation = validate_fold(&folds["validation"], critical)?;
    let combined_support = training.support + validation.support;
    if (combined_support - count_as_f64(support)?).abs() > 0.0
        || (training.estimate - validation.estimate).abs() > 0.05
        || !close(
            training.corrected_lower.min(validation.corrected_lower),
            lower,
            0.0,
        )
    {
        return Err(Error::new(
            "Automatic choice has inconsistent corrected outcomes",
        ));
    }
    Ok(())
}

#[derive(Debug)]
struct FoldDiagnostic {
    estimate: f64,
    corrected_lower: f64,
    support: f64,
}

fn validate_fold(row: &Value, critical: f64) -> Result<FoldDiagnostic> {
    object(row)?;
    let [low, high]: [f64; 2] = serde_json::from_value(row["interval"].clone())?;
    let estimate = finite(&row["estimate"], "automatic fold estimate")?;
    let radius = (high - low) / 2.0 / 1.96 * critical;
    let support = finite(&row["support"], "automatic fold support")?;
    let comparison = finite(
        &row["comparison_support"],
        "automatic fold comparison support",
    )?;
    let effective = finite(
        &row["effective_support"],
        "automatic fold effective support",
    )?;
    let overlap = finite(&row["overlap"], "automatic fold overlap")?;
    let balance = finite(
        &row["maximum_standardized_mean_difference"],
        "automatic fold balance",
    )?;
    if support.min(comparison) < 20.0
        || effective < 20.0
        || !(0.5..=1.0).contains(&overlap)
        || !(0.0..=0.1).contains(&balance)
        || !close(low.midpoint(high), estimate, 1.0e-12)
        || !(0.0..=0.05).contains(&radius)
        || estimate - radius <= 0.0
    {
        return Err(Error::new(
            "Automatic choice lacks sufficient support, overlap, balance, or corrected outcome evidence",
        ));
    }
    Ok(FoldDiagnostic {
        estimate,
        corrected_lower: estimate - radius,
        support,
    })
}
