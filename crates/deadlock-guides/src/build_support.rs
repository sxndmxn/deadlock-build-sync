use deadlock_data::{Error, Result, count_as_f64, count_ratio, object};
use serde_json::Value;

use crate::evidence_values::{close, finite, integer, nonnegative, probability};

#[derive(Clone, Copy, Debug)]
pub struct SupportPolicy {
    pub core_owners: u64,
    pub order_followers: u64,
    pub order_share: f64,
    pub pool_buyers: u64,
    pub pool_limit: usize,
}

pub const SUPPORT: SupportPolicy = SupportPolicy {
    core_owners: 100,
    order_followers: 20,
    order_share: 0.10,
    pool_buyers: 20,
    pool_limit: 10,
};

impl SupportPolicy {
    #[must_use]
    pub fn core_reasons(self, discovery: u64, selection: u64) -> Vec<String> {
        [("discovery", discovery), ("selection", selection)]
            .into_iter()
            .filter(|(_, count)| *count < self.core_owners)
            .map(|(fold, _)| format!("Fewer than {} {fold} core owners", self.core_owners))
            .collect()
    }

    /// # Errors
    /// Returns an error when an observation count cannot form a finite ratio.
    pub fn order_supported(self, owners: u64, followers: u64) -> Result<bool> {
        Ok(self.core_owners <= owners
            && self.order_followers <= followers
            && followers <= owners
            && count_ratio(followers, owners)? >= self.order_share)
    }
}

#[derive(Clone, Debug)]
pub struct OutcomeEvidence {
    pub owners: u64,
    pub win_rate: Option<f64>,
    pub win_lower: f64,
    pub win_p: f64,
    pub lift: f64,
    pub overlap: u64,
    pub overlap_share: f64,
    pub adjusted_lower: Option<f64>,
    pub adjusted_p: f64,
}

impl OutcomeEvidence {
    /// # Errors
    /// Returns an error when outcome counts, rates, comparisons, or uncertainty values are invalid.
    pub fn from_document(row: &Value) -> Result<Self> {
        object(row)?;
        object(&row["adjusted"])?;
        let owners = integer(&row["owners"], "core owners", 0)?;
        let win_rate = validate_outcome_rate(row, owners)?;
        let adjusted = &row["adjusted"];
        let overlap = integer(&adjusted["core_overlap"], "comparable core owners", 0)?;
        let overlap_share = finite(&adjusted["overlap_share"], "comparable state share")?;
        if overlap > owners || !close(overlap_share, count_ratio(overlap, owners.max(1))?, 0.0) {
            return Err(Error::new(
                "Discovery has inconsistent comparable state overlap",
            ));
        }
        Ok(Self {
            owners,
            win_rate,
            overlap,
            overlap_share,
            win_lower: probability(&row["win_lower_95"], "win lower bound")?,
            win_p: probability(&row["win_p_greater_half"], "win probability")?,
            lift: nonnegative(&row["joint_lift"], "joint ownership lift")?,
            adjusted_lower: validate_adjusted_outcome(adjusted)?,
            adjusted_p: probability(&adjusted["p_greater"], "adjusted probability")?,
        })
    }

    /// # Errors
    /// Returns an error when the hypothesis count cannot form a finite threshold.
    pub fn limitations(&self, hypotheses: Option<u64>) -> Result<Vec<String>> {
        let mut reasons = Vec::new();
        if self.owners < SUPPORT.core_owners {
            reasons.push("Fewer than 100 core owners".into());
        }
        if self.win_rate.is_none_or(|rate| rate < 0.52) {
            reasons.push("Observed win rate is below 52%".into());
        }
        if self.lift < 1.1 {
            reasons.push("Joint ownership lift is below 1.1".into());
        }
        if self.overlap < SUPPORT.core_owners || self.overlap_share < 0.8 {
            reasons.push("Comparable state overlap is insufficient".into());
        }
        if let Some(hypotheses) = hypotheses {
            let threshold = 0.025 / count_as_f64(hypotheses.max(1))?;
            if self.win_p > threshold {
                reasons.push("Win evidence fails family correction".into());
            }
            if self.adjusted_lower.is_none() || self.adjusted_p > threshold {
                reasons.push("Adjusted evidence fails family correction".into());
            }
        } else {
            if self.win_lower <= 0.5 {
                reasons.push("Win lower bound does not exceed 50%".into());
            }
            if self.adjusted_lower.is_none_or(|lower| lower <= 0.0) {
                reasons.push("Adjusted lower bound does not exceed zero".into());
            }
        }
        Ok(reasons)
    }
}

fn validate_outcome_rate(row: &Value, owners: u64) -> Result<Option<f64>> {
    let wins = integer(&row["wins"], "core wins", 0)?;
    if wins > owners {
        return Err(Error::new("Discovery core wins exceed its owners"));
    }
    if owners == 0 {
        if !row["win_rate"].is_null() {
            return Err(Error::new("Discovery has a win rate without core owners"));
        }
        return Ok(None);
    }
    let rate = finite(&row["win_rate"], "core win rate")?;
    if !close(rate, count_ratio(wins, owners)?, 0.0) {
        return Err(Error::new("Discovery has an inconsistent core win rate"));
    }
    Ok(Some(rate))
}

fn validate_adjusted_outcome(adjusted: &Value) -> Result<Option<f64>> {
    if adjusted["difference"].is_null() {
        if !adjusted["lower_95"].is_null() {
            return Err(Error::new("Discovery has an estimate without a contrast"));
        }
        return Ok(None);
    }
    finite(&adjusted["difference"], "adjusted difference")?;
    nonnegative(&adjusted["standard_error"], "adjusted standard error")?;
    finite(&adjusted["lower_95"], "adjusted lower bound").map(Some)
}
