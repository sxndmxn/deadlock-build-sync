use num_traits::ToPrimitive;
use serde::{Deserialize, Serialize};

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
