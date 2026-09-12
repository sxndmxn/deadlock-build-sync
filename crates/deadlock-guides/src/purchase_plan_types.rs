use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PurchaseStep {
    pub item_id: u64,
    pub name: String,
    pub incremental_cost: u64,
    pub cumulative_cost: u64,
    pub consumed_items: Vec<u64>,
    pub owned_after: Vec<u64>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PurchasePlan {
    pub actions: Vec<PurchaseStep>,
    pub final_inventory: Vec<u64>,
    pub remaining_cost: u64,
    pub decision: String,
    pub save_souls: Option<u64>,
}

#[derive(Clone, Debug, Default)]
pub struct PurchaseState {
    pub owned: Vec<u64>,
    pub liquid_souls: Option<u64>,
    pub flex: u8,
}
