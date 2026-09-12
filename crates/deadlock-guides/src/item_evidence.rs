use std::collections::BTreeMap;

use deadlock_data::Result;
use serde_json::Value;

use crate::item_evidence_content::ItemEvidenceContent;
use crate::item_evidence_validation::validate_item;

#[derive(Clone, Debug)]
pub struct ItemEvidence(ItemEvidenceContent);

impl ItemEvidence {
    /// # Errors
    /// Returns an error when item identity, observation counts, rates, purchase windows, or imbue evidence is invalid.
    pub fn from_document(value: &Value) -> Result<Self> {
        let mut content: ItemEvidenceContent = serde_json::from_value(value.clone())?;
        validate_item(&content)?;
        content.item = content.item.trim().into();
        content.slot = content.slot.trim().to_lowercase();
        content.imbue_target_ability = content.imbue_target_ability.map(|name| name.trim().into());
        Ok(Self(content))
    }

    #[must_use]
    pub const fn content(&self) -> &ItemEvidenceContent {
        &self.0
    }

    /// # Errors
    /// Returns an error when JSON serialization fails.
    pub fn to_document(&self) -> Result<Value> {
        Ok(serde_json::to_value(&self.0)?)
    }

    #[must_use]
    pub fn reliable_purchase_window(&self) -> Option<(f64, f64)> {
        let item = &self.0;
        if item.selection_valid_buy_net_worth_share < 0.5
            || item.training_valid_buy_net_worth_observations < 20
            || item.validation_valid_buy_net_worth_observations < 20
        {
            return None;
        }
        let lower = item.selection_buy_net_worth_q25?;
        let upper = item.selection_buy_net_worth_q75?;
        let train_lower = item.training_buy_net_worth_q25?;
        let train_upper = item.training_buy_net_worth_q75?;
        let validation_lower = item.validation_buy_net_worth_q25?;
        let validation_upper = item.validation_buy_net_worth_q75?;
        (train_lower.max(validation_lower) <= train_upper.min(validation_upper))
            .then_some((lower, upper))
    }
}

#[must_use]
pub fn nondecreasing_window_schedule(
    path: &[u64],
    bounds: &BTreeMap<u64, (f64, f64)>,
) -> Option<Vec<f64>> {
    let mut current = 0.0_f64;
    let mut result = Vec::with_capacity(path.len());
    for id in path {
        if let Some((lower, upper)) = bounds.get(id) {
            if !lower.is_finite() || !upper.is_finite() || lower > upper {
                return None;
            }
            current = current.max(*lower);
            if current > *upper {
                return None;
            }
        }
        result.push(current);
    }
    Some(result)
}
