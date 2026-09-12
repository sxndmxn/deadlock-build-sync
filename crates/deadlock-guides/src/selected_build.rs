use std::collections::BTreeMap;

use serde_json::Value;

use crate::automatic_branch::AutomaticBranch;
use crate::core_alternative::CoreAlternativeEvidence;
use crate::hero_cohort::HeroCohort;
use crate::item_evidence::ItemEvidence;
use crate::purchase_timing::PurchaseTiming;

#[derive(Clone, Debug)]
pub struct SelectedHeroBuild {
    pub hero_id: u64,
    pub path_id: String,
    pub path_label: String,
    pub signature_item_ids: Vec<u64>,
    pub core: Vec<ItemEvidence>,
    pub core_purchase_path: Vec<ItemEvidence>,
    pub tiers: BTreeMap<u8, Vec<ItemEvidence>>,
    pub backbone: Vec<ItemEvidence>,
    pub optional_core: Vec<ItemEvidence>,
    pub core_alternatives: Vec<CoreAlternativeEvidence>,
    pub backbone_matches: u64,
    pub backbone_share: f64,
    pub core_joint_matches: u64,
    pub core_joint_share: f64,
    pub median_final_net_worth: Option<u64>,
    pub core_target_cost: u64,
    pub evidence_summary: Value,
    pub purchase_timing: Vec<PurchaseTiming>,
    pub automatic_branches: Vec<AutomaticBranch>,
    pub cohort: HeroCohort,
}
