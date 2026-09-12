use num_traits::ToPrimitive;
use serde::{Deserialize, Serialize};
use statrs::distribution::{ContinuousCDF as _, Normal};

use crate::error::{Error, Result};

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
pub struct ObservationCounts {
    pub matches: u64,
    pub wins: u64,
    pub losses: u64,
}

impl ObservationCounts {
    /// # Errors
    /// Returns an error when wins and losses do not equal the match count.
    pub fn validate(self) -> Result<Self> {
        if self.wins.checked_add(self.losses) != Some(self.matches) {
            return Err(Error::new(
                "Observation wins and losses must equal the match count",
            ));
        }
        Ok(self)
    }

    /// # Errors
    /// Returns an error when an observation count exceeds 64 bits.
    pub fn checked_add(self, other: Self) -> Result<Self> {
        let add = |first: u64, second: u64| {
            first
                .checked_add(second)
                .ok_or_else(|| Error::new("Combined observation count exceeds 64 bits"))
        };
        Ok(Self {
            matches: add(self.matches, other.matches)?,
            wins: add(self.wins, other.wins)?,
            losses: add(self.losses, other.losses)?,
        })
    }

    /// # Errors
    /// Returns an error when a count cannot be converted to a finite floating point number.
    pub fn win_rate(self) -> Result<f64> {
        count_ratio(self.wins, self.matches)
    }
}

/// # Errors
/// Returns an error when the count cannot be converted to a finite floating point number.
pub fn count_as_f64(count: u64) -> Result<f64> {
    count
        .to_f64()
        .filter(|value| value.is_finite())
        .ok_or_else(|| Error::new("Observation count cannot be represented as a finite number"))
}

/// # Errors
/// Returns an error when a count cannot be converted to a finite floating point number.
pub fn count_ratio(numerator: u64, denominator: u64) -> Result<f64> {
    if denominator == 0 {
        return Ok(0.0);
    }
    Ok(count_as_f64(numerator)? / count_as_f64(denominator)?)
}

/// # Errors
/// Returns an error when a probability is invalid or its rounded observation count exceeds the population.
pub fn count_from_probability(probability: f64, population: u64) -> Result<u64> {
    if !(0.0..=1.0).contains(&probability) {
        return Err(Error::new(
            "Observation probability must be between zero and one",
        ));
    }
    (probability * count_as_f64(population)?)
        .round_ties_even()
        .to_u64()
        .filter(|count| *count <= population)
        .ok_or_else(|| Error::new("Rounded observation count exceeds the population"))
}

/// # Errors
/// Returns an error for a nonfinite value or more than 15 decimal places.
pub fn round_decimal(value: f64, places: usize) -> Result<f64> {
    if !value.is_finite() || places > 15 {
        return Err(Error::new(
            "Decimal rounding requires a finite value and at most 15 decimal places",
        ));
    }
    format!("{value:.places$}")
        .parse()
        .map_err(|error| Error::new(format!("Cannot round decimal value: {error}")))
}

/// # Errors
/// Returns an error when probability is outside the open unit interval or its quantile is not finite.
pub fn normal_quantile(probability: f64) -> Result<f64> {
    if !probability.is_finite() || probability <= 0.0 || probability >= 1.0 {
        return Err(Error::new(
            "Normal quantile requires a probability strictly between zero and one",
        ));
    }
    let distribution = Normal::new(0.0, 1.0).map_err(|error| Error::new(error.to_string()))?;
    let quantile = distribution.inverse_cdf(probability);
    if !quantile.is_finite() {
        return Err(Error::new("Normal quantile is not finite"));
    }
    Ok(quantile)
}
