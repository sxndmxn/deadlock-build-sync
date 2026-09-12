use deadlock_data::{ObservationCounts, Result, count_ratio};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct AbilityPath {
    pub ability_ids: Vec<u64>,
    pub matches: u64,
    pub wins: u64,
    pub losses: u64,
    pub cohort_matches: u64,
    pub complete_path_matches: u64,
    pub decision_support: Vec<u64>,
    pub selection: String,
    pub filter_item_ids: Vec<u64>,
    pub fallback_reason: Option<String>,
}

impl AbilityPath {
    #[must_use]
    pub fn minimum_decision_support(&self) -> u64 {
        self.decision_support
            .iter()
            .copied()
            .min()
            .unwrap_or(self.matches)
    }

    /// # Errors
    /// Returns an error when an observation count cannot be converted to a finite number.
    pub fn final_branch_support_share(&self) -> Result<f64> {
        count_ratio(self.matches, self.cohort_matches)
    }

    /// # Errors
    /// Returns an error when an observation count cannot be converted to a finite number.
    pub fn observed_final_branch_outcome_rate(&self) -> Result<f64> {
        ObservationCounts {
            matches: self.matches,
            wins: self.wins,
            losses: self.losses,
        }
        .win_rate()
    }

    #[must_use]
    pub fn quality_assessment(&self) -> Value {
        let supported = self.minimum_decision_support() >= 20;
        let compatible = !self.filter_item_ids.is_empty() && self.fallback_reason.is_none();
        let status = if !supported {
            "fail"
        } else if compatible {
            "pass"
        } else {
            "unevaluated"
        };
        json!({"status":status, "minimum_decision_support":self.minimum_decision_support(), "required_decision_support":20, "build_conditioned":compatible, "fallback_reason":self.fallback_reason, "claim":"supported observed order; tactical superiority is not established"})
    }

    #[must_use]
    pub fn annotation(&self) -> String {
        let prefix = if self.minimum_decision_support() < 20 {
            "Low final decision support. "
        } else {
            ""
        };
        format!(
            "{prefix}Observed ability order. Final decision support: n={}. The data does not establish tactical superiority.",
            self.matches
        )
    }
}
