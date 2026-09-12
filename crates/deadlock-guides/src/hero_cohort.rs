use deadlock_data::{Error, Rank, RankRange, Result, array, object};
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::evidence_values::{integer, nonempty_text};

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum RankExpansion {
    Auto,
    Off,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct HeroCohortContent {
    pub minimum_badge: Rank,
    pub maximum_badge: Rank,
    pub rank_expansion: RankExpansion,
    pub expansion_history: Vec<Value>,
}

#[derive(Clone, Debug)]
pub struct HeroCohort(HeroCohortContent);

impl HeroCohort {
    /// # Errors
    /// Returns an error when the rank history has missing steps or continues after a supported build.
    pub fn from_document(value: &Value) -> Result<Self> {
        let content: HeroCohortContent = serde_json::from_value(value.clone())?;
        let history = array(&value["expansion_history"])?;
        let first = history.first().ok_or_else(|| {
            Error::new("Hero has no rank expansion history; run refresh-evidence")
        })?;
        let starting_badge = Rank::try_from(u16::try_from(integer(
            &first["minimum_badge"],
            "starting rank badge",
            1,
        )?)?)?;
        let cutoffs = calculate_rank_cutoffs(
            starting_badge,
            content.maximum_badge,
            content.rank_expansion,
        )?;
        if history.len() > cutoffs.len() || cutoffs[history.len() - 1] != content.minimum_badge {
            return Err(Error::new("Hero has inconsistent effective ranks"));
        }
        for (index, attempt) in history.iter().enumerate() {
            validate_attempt(
                attempt,
                cutoffs[index],
                content.maximum_badge,
                index + 1 == history.len(),
            )?;
        }
        Ok(Self(content))
    }

    #[must_use]
    pub const fn content(&self) -> &HeroCohortContent {
        &self.0
    }

    /// # Errors
    /// Returns an error when JSON serialization fails.
    pub fn to_document(&self) -> Result<Value> {
        Ok(serde_json::to_value(&self.0)?)
    }

    /// # Errors
    /// Returns an error when the rank range is invalid.
    pub fn rank_range(&self) -> Result<RankRange> {
        RankRange {
            minimum: self.0.minimum_badge,
            maximum: self.0.maximum_badge,
        }
        .validate()
    }
}

/// # Errors
/// Returns an error when the minimum rank exceeds the maximum rank.
pub fn calculate_rank_cutoffs(
    minimum: Rank,
    maximum: Rank,
    mode: RankExpansion,
) -> Result<Vec<Rank>> {
    RankRange { minimum, maximum }.validate()?;
    let mut cutoffs = vec![minimum];
    if mode == RankExpansion::Off || minimum.badge() == 11 {
        return Ok(cutoffs);
    }
    for tier in (1..minimum.tier()).rev() {
        cutoffs.push(Rank::try_from(tier * 10 + 1)?);
    }
    if cutoffs.len() == 1 {
        cutoffs.push(Rank::try_from(11)?);
    }
    Ok(cutoffs)
}

fn validate_attempt(attempt: &Value, minimum: Rank, maximum: Rank, last: bool) -> Result<()> {
    object(attempt)?;
    if integer(&attempt["minimum_badge"], "attempt minimum rank", 1)? != u64::from(minimum.badge())
        || integer(&attempt["maximum_badge"], "attempt maximum rank", 1)?
            != u64::from(maximum.badge())
    {
        return Err(Error::new(
            "Hero rank expansion skipped a tier or changed its maximum rank",
        ));
    }
    for key in [
        "discovery_rows",
        "selection_rows",
        "candidate_count",
        "discovery_owners",
        "selection_owners",
    ] {
        integer(&attempt[key], key, 0)?;
    }
    let builds = integer(&attempt["supported_builds"], "supported builds", 0)?;
    if (builds > 0) != last {
        return Err(Error::new(
            "Hero expanded after support or has no supported build",
        ));
    }
    let reason = if last {
        "supported build available"
    } else {
        "no supported legal path"
    };
    if nonempty_text(&attempt["reason"], "rank expansion reason")? != reason {
        return Err(Error::new("Hero rank expansion has an invalid reason"));
    }
    Ok(())
}
