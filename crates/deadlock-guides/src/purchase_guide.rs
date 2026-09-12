use std::collections::BTreeMap;

use deadlock_data::{Error, Result};
use serde_json::Value;

use crate::ability_path::AbilityPath;
use crate::automatic_branch::AutomaticBranch;
use crate::core_alternative::CoreAlternativeEvidence;
use crate::guide_category::{
    CORE_CATEGORY_DESCRIPTION, GuideCategory, OPTIONAL_CORE_CATEGORY_DESCRIPTION,
};
use crate::guide_item::GuideItem;
use crate::hero_cohort::HeroCohort;
use crate::purchase_guidance_types::PurchaseGuidance;
use crate::purchase_timing::PurchaseTiming;
use crate::selected_build::SelectedHeroBuild;

#[derive(Clone, Debug)]
pub struct TacticalProfile {
    pub primary_role: String,
    pub fight_role: String,
    pub economy_plan: String,
}

#[derive(Clone, Debug)]
pub struct PurchaseGuide {
    pub hero_id: u64,
    pub hero_name: String,
    pub hero_class_name: String,
    pub tiers: BTreeMap<u8, Vec<GuideItem>>,
    pub path_id: String,
    pub path_label: String,
    pub signature_item_ids: Vec<u64>,
    pub ability_path: Option<AbilityPath>,
    pub summary: String,
    pub tactical_profile: Option<TacticalProfile>,
    pub tier_summaries: BTreeMap<u8, String>,
    pub categories: Vec<GuideCategory>,
    pub snapshot_id: String,
    pub policy_id: String,
    pub client_version: Option<u64>,
    pub match_mode: String,
    pub rank_identity: String,
    pub core_items: Vec<GuideItem>,
    pub core_purchase_items: Vec<GuideItem>,
    pub backbone_items: Vec<GuideItem>,
    pub optional_core_items: Vec<GuideItem>,
    pub core_alternatives: Vec<CoreAlternativeEvidence>,
    pub backbone_matches: u64,
    pub backbone_share: f64,
    pub core_joint_matches: u64,
    pub core_joint_share: f64,
    pub median_final_net_worth: Option<u64>,
    pub core_target_cost: u64,
    pub build_tag_ids: Vec<u64>,
    pub build_tag_classes: Vec<String>,
    pub build_tag_labels: Vec<String>,
    pub build_tag_catalog_sha256: String,
    pub build_archetype: String,
    pub analysis_start_timestamp: u64,
    pub as_of_timestamp: u64,
    pub cohort: Option<HeroCohort>,
    pub evidence_summary: Value,
    pub purchase_timing: Vec<PurchaseTiming>,
    pub purchase_guidance: Option<PurchaseGuidance>,
    pub automatic_branches: Vec<AutomaticBranch>,
    pub variant_guides: Vec<Self>,
}

impl Default for PurchaseGuide {
    fn default() -> Self {
        Self {
            hero_id: 0,
            hero_name: String::new(),
            hero_class_name: String::new(),
            tiers: BTreeMap::new(),
            path_id: "default".into(),
            path_label: "Evidence Default".into(),
            signature_item_ids: Vec::new(),
            ability_path: None,
            summary: String::new(),
            tactical_profile: None,
            tier_summaries: BTreeMap::new(),
            categories: Vec::new(),
            snapshot_id: String::new(),
            policy_id: String::new(),
            client_version: None,
            match_mode: String::new(),
            rank_identity: String::new(),
            core_items: Vec::new(),
            core_purchase_items: Vec::new(),
            backbone_items: Vec::new(),
            optional_core_items: Vec::new(),
            core_alternatives: Vec::new(),
            backbone_matches: 0,
            backbone_share: 0.0,
            core_joint_matches: 0,
            core_joint_share: 0.0,
            median_final_net_worth: Some(0),
            core_target_cost: 0,
            build_tag_ids: Vec::new(),
            build_tag_classes: Vec::new(),
            build_tag_labels: Vec::new(),
            build_tag_catalog_sha256: String::new(),
            build_archetype: "Evidence Default".into(),
            analysis_start_timestamp: 0,
            as_of_timestamp: 0,
            cohort: None,
            evidence_summary: serde_json::json!({}),
            purchase_timing: Vec::new(),
            purchase_guidance: None,
            automatic_branches: Vec::new(),
            variant_guides: Vec::new(),
        }
    }
}

impl PurchaseGuide {
    /// # Errors
    /// Returns an error when the selected build and hero asset have different identities.
    pub fn from_selected(
        hero: &Value,
        selected: &SelectedHeroBuild,
        ability_path: Option<AbilityPath>,
    ) -> Result<Self> {
        if hero["id"].as_u64() != Some(selected.hero_id) {
            return Err(Error::new("Selected build differs from its hero asset"));
        }
        Ok(Self {
            hero_id: selected.hero_id,
            hero_name: hero["name"]
                .as_str()
                .filter(|name| !name.is_empty())
                .map_or_else(|| format!("Hero {}", selected.hero_id), str::to_owned),
            hero_class_name: hero["class_name"].as_str().unwrap_or_default().into(),
            tiers: selected
                .tiers
                .iter()
                .map(|(tier, items)| (*tier, items.iter().map(GuideItem::from_evidence).collect()))
                .collect(),
            path_id: selected.path_id.clone(),
            path_label: selected.path_label.clone(),
            signature_item_ids: selected.signature_item_ids.clone(),
            ability_path,
            core_items: selected.core.iter().map(GuideItem::from_evidence).collect(),
            core_purchase_items: selected
                .core_purchase_path
                .iter()
                .map(GuideItem::from_evidence)
                .collect(),
            backbone_items: selected
                .backbone
                .iter()
                .map(GuideItem::from_evidence)
                .collect(),
            optional_core_items: selected
                .optional_core
                .iter()
                .map(GuideItem::from_evidence)
                .collect(),
            core_alternatives: selected.core_alternatives.clone(),
            backbone_matches: selected.backbone_matches,
            backbone_share: selected.backbone_share,
            core_joint_matches: selected.core_joint_matches,
            core_joint_share: selected.core_joint_share,
            median_final_net_worth: selected.median_final_net_worth,
            core_target_cost: selected.core_target_cost,
            build_archetype: "Evidence Default".into(),
            cohort: Some(selected.cohort.clone()),
            evidence_summary: selected.evidence_summary.clone(),
            purchase_timing: selected.purchase_timing.clone(),
            automatic_branches: selected.automatic_branches.clone(),
            ..Self::default()
        })
    }

    #[must_use]
    pub fn core_path_items(&self) -> &[GuideItem] {
        if self.core_purchase_items.is_empty() {
            &self.core_items
        } else {
            &self.core_purchase_items
        }
    }

    #[must_use]
    pub fn item_count(&self) -> usize {
        if self.categories.is_empty() {
            self.core_items.len() + self.tiers.values().map(Vec::len).sum::<usize>()
        } else {
            self.categories
                .iter()
                .map(|category| category.items.len())
                .sum()
        }
    }

    #[must_use]
    pub fn has_complete_item_coverage(&self) -> bool {
        (!self.core_items.is_empty()
            && self.tiers.keys().copied().collect::<Vec<_>>() == [1, 2, 3, 4])
            || (1..=4).all(|tier| self.tiers.get(&tier).is_some_and(|items| !items.is_empty()))
    }

    /// # Errors
    /// Returns an error when category dimensions exceed their limits.
    pub fn rendered_categories(&self) -> Result<Vec<GuideCategory>> {
        if !self.categories.is_empty() {
            return Ok(self.categories.clone());
        }
        if self.core_items.is_empty() {
            return self.aggregate_categories();
        }
        let mut result = vec![GuideCategory::new(
            "CORE ITEMS".into(),
            self.core_path_items().into(),
            CORE_CATEGORY_DESCRIPTION.into(),
            false,
            false,
        )?];
        if !self.optional_core_items.is_empty() {
            result.push(GuideCategory::new(
                "OPTIONAL CORE".into(),
                self.optional_core_items.clone(),
                OPTIONAL_CORE_CATEGORY_DESCRIPTION.into(),
                true,
                false,
            )?);
        }
        for tier in 1..=4 {
            result.push(GuideCategory::new(
                format!("TIER {tier}"),
                self.tiers.get(&tier).cloned().unwrap_or_default(),
                String::new(),
                true,
                false,
            )?);
        }
        Ok(result)
    }

    fn aggregate_categories(&self) -> Result<Vec<GuideCategory>> {
        let mut result = Vec::new();
        for (tier, items) in &self.tiers {
            let Some((first, rest)) = items.split_first() else {
                continue;
            };
            result.push(GuideCategory::new(
                format!("CORE {tier}"),
                vec![first.clone()],
                self.tier_summaries.get(tier).cloned().unwrap_or_default(),
                false,
                false,
            )?);
            if !rest.is_empty() {
                result.push(GuideCategory::new(
                    format!("OPTIONS {tier}"),
                    rest.into(),
                    "Situational alternatives; choose only when their trigger applies.".into(),
                    true,
                    false,
                )?);
            }
        }
        Ok(result)
    }
}
