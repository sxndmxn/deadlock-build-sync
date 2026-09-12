use deadlock_data::{Error, Result};
use serde_json::Value;

use crate::mechanics_assets::{positive_identifier, required_class};

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ItemNode {
    pub item_id: u64,
    pub class_name: String,
    pub name: String,
    pub cost: u64,
    pub slot: String,
    pub tier: u8,
    pub component_classes: Vec<String>,
    pub active: bool,
    pub unique: bool,
    pub max_count: u32,
}

impl ItemNode {
    /// # Errors
    /// Returns an error when an available item has invalid identifiers, components, or mechanics fields.
    pub fn from_asset(asset: &Value) -> Result<Option<Self>> {
        if !read_boolean(asset, "shopable", false)? || read_boolean(asset, "disabled", false)? {
            return Ok(None);
        }
        let item_id = positive_identifier(asset)?;
        let class_name = required_class(asset)?.to_owned();
        let name = asset["name"]
            .as_str()
            .filter(|name| !name.is_empty())
            .unwrap_or(&class_name)
            .to_owned();
        Ok(Some(Self {
            item_id,
            name,
            class_name,
            cost: read_nonnegative(asset, "cost", 0)?,
            slot: asset["item_slot_type"]
                .as_str()
                .filter(|slot| !slot.is_empty())
                .unwrap_or("unknown")
                .to_lowercase(),
            tier: u8::try_from(read_nonnegative(asset, "item_tier", 0)?)?,
            component_classes: read_components(asset)?,
            active: read_boolean(asset, "is_active_item", false)?,
            unique: read_boolean(asset, "is_unique", true)?,
            max_count: u32::try_from(read_nonnegative(asset, "max_count", 1)?.max(1))?,
        }))
    }
}

fn read_components(asset: &Value) -> Result<Vec<String>> {
    let Some(value) = asset
        .get("component_items")
        .filter(|value| !value.is_null())
    else {
        return Ok(Vec::new());
    };
    value
        .as_array()
        .ok_or_else(|| Error::new("Item components must be an array"))?
        .iter()
        .map(|value| {
            value
                .as_str()
                .filter(|value| !value.is_empty())
                .map(str::to_owned)
                .ok_or_else(|| Error::new("Item component must be a class name"))
        })
        .collect()
}

fn read_boolean(asset: &Value, name: &str, default: bool) -> Result<bool> {
    asset
        .get(name)
        .filter(|value| !value.is_null())
        .map_or(Ok(default), |value| {
            value
                .as_bool()
                .ok_or_else(|| Error::new(format!("Item field must be Boolean: {name}")))
        })
}

fn read_nonnegative(asset: &Value, name: &str, default: u64) -> Result<u64> {
    asset
        .get(name)
        .filter(|value| !value.is_null())
        .map_or(Ok(default), |value| {
            value.as_u64().ok_or_else(|| {
                Error::new(format!("Item field must be a nonnegative integer: {name}"))
            })
        })
}
