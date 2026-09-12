use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum RecommendationAction {
    Buy,
    Save,
    End,
    #[default]
    Abstain,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Recommendation {
    pub action: RecommendationAction,
    pub hero_id: u64,
    pub policy_id: String,
    pub item_id: Option<u64>,
    pub target_item_id: Option<u64>,
    pub incremental_cost: Option<u64>,
    pub support: Option<u64>,
    pub support_share: Option<f64>,
    pub backoff_level: Option<String>,
    pub reason: String,
    pub counter: Option<Value>,
    pub purchase_plan: Option<Value>,
}

impl Recommendation {
    #[must_use]
    pub fn abstain(hero_id: u64, policy_id: &str, reason: String) -> Self {
        Self {
            hero_id,
            policy_id: policy_id.into(),
            reason,
            ..Self::default()
        }
    }
}
