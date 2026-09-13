use deadlock_data::{Error, Result};

use crate::guide_category::GuideCategory;
use crate::purchase_guide::PurchaseGuide;
use crate::purchase_prefix::{purchase_items, shared_prefix_length};
use crate::variant_items::{collect_group_item_ids, collect_tier_items};

fn build_variant_categories(guide: &PurchaseGuide) -> Result<Vec<GuideCategory>> {
    let Some(first) = guide.variant_guides.first() else {
        return Ok(Vec::new());
    };
    let length = shared_prefix_length(&guide.variant_guides)?;
    if length == 0 {
        return Err(Error::new(
            "Variants require a shared purchase prefix and separate continuations",
        ));
    }
    let mut result = vec![GuideCategory::new(
        "ALT CORE".into(),
        purchase_items(first, "Stats: VARIANT 1.\n")?[..length].to_vec(),
        String::new(),
        true,
        true,
    )?];
    for (index, variant) in guide.variant_guides.iter().enumerate() {
        result.push(GuideCategory::new(
            format!("VARIANT {}", index + 1),
            purchase_items(variant, "")?[length..].to_vec(),
            String::new(),
            true,
            true,
        )?);
    }
    Ok(result)
}

/// # Errors
/// Returns an error when purchase paths, variant prefixes, item statistics, or category dimensions are invalid.
pub fn build_compact_categories(guide: &PurchaseGuide) -> Result<Vec<GuideCategory>> {
    let core = purchase_items(guide, "")?;
    let mut result = vec![GuideCategory::new(
        "MAIN CORE".into(),
        core,
        String::new(),
        false,
        true,
    )?];
    result.extend(build_variant_categories(guide)?);
    for tier in 1..=4 {
        let items = collect_tier_items(guide, tier)?;
        let description = if items.is_empty() {
            "No supported options."
        } else {
            ""
        };
        result.push(GuideCategory::new(
            format!("TIER {tier}"),
            items,
            description.into(),
            true,
            true,
        )?);
    }
    Ok(result)
}

/// # Errors
/// Returns an error when panels, annotations, dimensions, queue flags, or purchases differ from the admitted paths.
pub fn validate_group_categories(guide: &PurchaseGuide) -> Result<()> {
    let categories = guide.rendered_categories()?;
    let expected = build_compact_categories(guide)?;
    if serde_json::to_value(&categories)? != serde_json::to_value(&expected)? {
        return Err(Error::new(
            "Steam panels differ from the complete admitted purchase paths",
        ));
    }
    let shown = categories
        .iter()
        .flat_map(|category| &category.items)
        .map(|item| item.item_id)
        .collect();
    if collect_group_item_ids(guide) != shown {
        return Err(Error::new(
            "Steam build items differ from the complete supported items",
        ));
    }
    Ok(())
}
