use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::automatic_branch::AutomaticBranch;
use crate::purchase_plan_types::PurchasePlan;
use crate::purchase_timing::PurchaseTiming;

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ItemPurpose {
    pub label: String,
    pub trigger: String,
    pub evidence: String,
    pub basis: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PurchaseChoice {
    pub item_id: u64,
    pub name: String,
    pub tier: u8,
    pub catalog_cost: u64,
    pub purpose: ItemPurpose,
    pub after_step: Option<usize>,
    pub timing: Option<PurchaseTiming>,
    pub timing_basis: String,
    pub route: Vec<u64>,
    pub upgrades_core: Vec<u64>,
    pub plan: Option<PurchasePlan>,
    pub blocked_reason: Option<String>,
    pub extra_path_cost: Option<i128>,
    pub rebought_components: Vec<u64>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PurchaseDecision {
    pub after_step: usize,
    pub kind: String,
    pub purpose: String,
    pub options: Vec<u64>,
    pub upgrade_fork: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PurchaseGuidance {
    pub core_ids: Vec<u64>,
    pub default_path: PurchasePlan,
    pub choices: Vec<PurchaseChoice>,
    pub decisions: Vec<PurchaseDecision>,
    pub names: BTreeMap<u64, String>,
    pub evidence_basis: String,
    pub schema_version: u8,
    pub cohort: Value,
    pub evidence: Value,
    pub automatic_branches: Vec<AutomaticBranch>,
}
