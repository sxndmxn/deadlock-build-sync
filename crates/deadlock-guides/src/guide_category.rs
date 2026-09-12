use deadlock_data::{Error, Result};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

use crate::guide_item::GuideItem;

pub const MAX_CATEGORY_DESCRIPTION_BYTES: usize = 240;
pub const CORE_CATEGORY_DESCRIPTION: &str = "AUTO QUEUE • Default path, buy left→right.";
pub const OPTIONAL_CORE_CATEGORY_DESCRIPTION: &str =
    "Excluded from Queue • Swap only when the card trigger applies.";

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct GuideCategory {
    pub name: String,
    pub items: Vec<GuideItem>,
    pub description: String,
    pub optional: bool,
    pub compact: bool,
    pub width: f32,
    pub height: f32,
}

impl GuideCategory {
    /// # Errors
    /// Returns an error when the category exceeds 4096 items or its layout dimensions cannot be represented.
    pub fn new(
        name: String,
        items: Vec<GuideItem>,
        description: String,
        optional: bool,
        compact: bool,
    ) -> Result<Self> {
        if items.len() > 4096 {
            return Err(Error::new("Category exceeds 4096 items"));
        }
        let (width, columns) = match name.as_str() {
            "CORE ITEMS" => (567.0, 6),
            "OPTIONAL CORE" | "TIER 1" | "TIER 3" => (465.75, 5),
            "TIER 2" => (562.5, 5),
            "TIER 4" => (1039.5, 10),
            _ => (760.0, 8),
        };
        let columns = if compact {
            items.len().clamp(1, if items.len() <= 18 { 6 } else { 12 })
        } else {
            columns
        };
        let width = if compact {
            if items.is_empty() {
                256.0
            } else {
                84.0_f32
                    .mul_add(f32::from(u16::try_from(columns)?), 12.0)
                    .max(128.0)
            }
        } else {
            width
        };
        let rows = items.len().div_ceil(columns).max(1);
        let extra_height =
            (if compact { 129.0 } else { 155.5 }) * f32::from(u16::try_from(rows - 1)?);
        let height = if compact && items.is_empty() {
            48.0
        } else {
            164.0 + extra_height
        };
        Ok(Self {
            name,
            items,
            description,
            optional,
            compact,
            width,
            height,
        })
    }

    #[must_use]
    pub fn record(&self) -> Value {
        json!({
            "name": self.name, "optional": self.optional, "description": self.description,
            "width": self.width, "height": self.height,
            "items": self.items.iter().map(|item| json!({
                "item_id": item.item_id, "item": item.name, "annotation": item.annotation(),
                "required_flex_slots": item.required_flex_slots, "sell_priority": item.sell_priority,
                "imbue_target_ability_id": item.imbue_target_ability_id,
            })).collect::<Vec<_>>(),
        })
    }
}

#[must_use]
pub fn standard_category_description(name: &str) -> Option<&'static str> {
    match name {
        "CORE ITEMS" => Some(CORE_CATEGORY_DESCRIPTION),
        "OPTIONAL CORE" => Some(OPTIONAL_CORE_CATEGORY_DESCRIPTION),
        "TIER 1" | "TIER 2" | "TIER 3" | "TIER 4" => Some(""),
        _ => None,
    }
}
