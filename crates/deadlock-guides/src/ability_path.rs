use serde::{Deserialize, Serialize};

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
