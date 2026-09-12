use deadlock_data::{Error, Result};
use serde_json::Value;

pub fn integer(value: &Value, label: &str, minimum: u64) -> Result<u64> {
    value
        .as_u64()
        .filter(|value| *value >= minimum)
        .ok_or_else(|| Error::new(format!("Evidence has an invalid integer: {label}")))
}

pub fn finite(value: &Value, label: &str) -> Result<f64> {
    value
        .as_f64()
        .filter(|number| number.is_finite())
        .ok_or_else(|| Error::new(format!("Evidence has an invalid finite number: {label}")))
}

pub fn nonnegative(value: &Value, label: &str) -> Result<f64> {
    let number = finite(value, label)?;
    if number < 0.0 {
        return Err(Error::new(format!(
            "Evidence has a negative number: {label}"
        )));
    }
    Ok(number)
}

pub fn probability(value: &Value, label: &str) -> Result<f64> {
    let number = finite(value, label)?;
    if !(0.0..=1.0).contains(&number) {
        return Err(Error::new(format!(
            "Evidence probability is outside zero to one: {label}"
        )));
    }
    Ok(number)
}

pub fn nonempty_text<'value>(value: &'value Value, label: &str) -> Result<&'value str> {
    value
        .as_str()
        .map(str::trim)
        .filter(|text| !text.is_empty())
        .ok_or_else(|| Error::new(format!("Evidence has an invalid text field: {label}")))
}

pub fn close(left: f64, right: f64, absolute_tolerance: f64) -> bool {
    left.is_finite()
        && right.is_finite()
        && (left - right).abs() <= absolute_tolerance.max(1.0e-9 * left.abs().max(right.abs()))
}

pub fn add_counts(left: u64, right: u64) -> Result<u64> {
    left.checked_add(right)
        .ok_or_else(|| Error::new("Evidence count exceeds 64 bits"))
}
