use std::collections::BTreeSet;

use deadlock_data::{Error, Result};

use crate::beam_display::variant_statistics;
use crate::guide_category::GuideCategory;
use crate::guide_item::format_integer;
use crate::purchase_guide::PurchaseGuide;
use crate::variant_items::{
    collect_conditional_items, collect_group_item_ids, collect_tier_items, collect_variant_items,
    group_members,
};

fn build_variant_categories(guide: &PurchaseGuide) -> Result<Vec<GuideCategory>> {
    if guide.variant_guides.is_empty() {
        return Ok(Vec::new());
    }
    let mut shared = guide
        .core_items
        .iter()
        .map(|item| item.item_id)
        .collect::<BTreeSet<_>>();
    for member in &guide.variant_guides {
        shared.retain(|id| member.core_items.iter().any(|item| item.item_id == *id));
    }
    let mut result = Vec::new();
    if !shared.is_empty() {
        let members = group_members(guide)
            .enumerate()
            .flat_map(|(index, member)| {
                let scope = if index == 0 {
                    "Default".into()
                } else {
                    format!("V{index}")
                };
                let shared = &shared;
                member
                    .core_items
                    .iter()
                    .filter(move |item| shared.contains(&item.item_id))
                    .map(move |item| (item, scope.clone()))
            })
            .collect();
        result.push(GuideCategory::new(
            "ALTERNATIVE CORE".into(),
            collect_variant_items(members),
            "Combine with one VARIANT.".into(),
            true,
            true,
        )?);
    }
    for (index, member) in guide.variant_guides.iter().enumerate() {
        let combination = member
            .core_items
            .iter()
            .filter(|item| !shared.contains(&item.item_id))
            .collect::<Vec<_>>();
        let mut description = vec![if !shared.is_empty() && !combination.is_empty() {
            "ALTERNATIVE CORE +".into()
        } else {
            "Full core.".into()
        }];
        let statistics = variant_statistics(member, false)?;
        description.extend(if statistics.is_empty() {
            vec!["State evidence unavailable.".into()]
        } else {
            statistics
        });
        let items = if combination.is_empty() {
            member.core_items.iter().collect()
        } else {
            combination
        };
        let items = collect_variant_items(
            items
                .into_iter()
                .map(|item| (item, format!("V{}", index + 1)))
                .collect(),
        );
        result.push(GuideCategory::new(
            format!("VARIANT {}", index + 1),
            items,
            description.join("\n"),
            true,
            true,
        )?);
    }
    Ok(result)
}

pub fn build_compact_categories(guide: &PurchaseGuide) -> Result<Vec<GuideCategory>> {
    let Some(guidance) = &guide.purchase_guidance else {
        return guide.rendered_categories();
    };
    if guide.core_path_items().len() != guidance.default_path.actions.len() {
        return Err(Error::new("Core item count differs from its purchase path"));
    }
    let core = guide
        .core_path_items()
        .iter()
        .zip(&guidance.default_path.actions)
        .enumerate()
        .map(|(index, (item, step))| {
            let mut item = item.clone();
            item.annotation_text = format!(
                "Step {}: +{} souls; total {}.\n{}",
                index + 1,
                format_integer(i128::from(step.incremental_cost)),
                format_integer(i128::from(step.cumulative_cost)),
                item.annotation()
            );
            item
        })
        .collect::<Vec<_>>();
    let conditional = collect_conditional_items(guide);
    let covered = core
        .iter()
        .chain(&conditional)
        .map(|item| item.item_id)
        .collect();
    let mut result = vec![GuideCategory::new(
        "CORE ITEMS".into(),
        core,
        variant_statistics(guide, false)?.join("; "),
        false,
        true,
    )?];
    result.extend(build_variant_categories(guide)?);
    if !conditional.is_empty() {
        result.push(GuideCategory::new(
            "CORE CONDITIONAL".into(),
            conditional,
            String::new(),
            true,
            true,
        )?);
    }
    for tier in 1..=4 {
        let items = collect_tier_items(guide, tier, &covered);
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
/// Returns an error when category names, variants, queue order, or item coverage differ from the complete group.
pub fn validate_group_categories(guide: &PurchaseGuide) -> Result<()> {
    let categories = guide.rendered_categories()?;
    let Some(guidance) = &guide.purchase_guidance else {
        return Ok(());
    };
    if !categories.iter().any(|category| category.compact) {
        return Ok(());
    }
    let variants = build_variant_categories(guide)?;
    let mut expected = vec!["CORE ITEMS".to_owned()];
    expected.extend(variants.iter().map(|category| category.name.clone()));
    if !collect_conditional_items(guide).is_empty() {
        expected.push("CORE CONDITIONAL".into());
    }
    expected.extend((1..=4).map(|tier| format!("TIER {tier}")));
    if !categories
        .iter()
        .map(|category| &category.name)
        .eq(expected.iter())
    {
        return Err(Error::new(
            "Steam build requires the core, each variant, and all four tier panels",
        ));
    }
    let shown_variants = categories.get(1..=variants.len()).unwrap_or_default();
    if serde_json::to_value(shown_variants)? != serde_json::to_value(&variants)? {
        return Err(Error::new(
            "Steam variant panels differ from complete core combinations",
        ));
    }
    if categories
        .iter()
        .enumerate()
        .any(|(index, category)| category.optional != (index > 0))
    {
        return Err(Error::new(
            "Steam tier and variant panels must remain optional",
        ));
    }
    let core = categories
        .first()
        .ok_or_else(|| Error::new("Steam build has no core category"))?;
    if !core.items.iter().map(|item| item.item_id).eq(guidance
        .default_path
        .actions
        .iter()
        .map(|step| step.item_id))
    {
        return Err(Error::new(
            "Steam Queue differs from the canonical component path",
        ));
    }
    let shown = categories
        .iter()
        .flat_map(|category| &category.items)
        .map(|item| item.item_id)
        .collect();
    if collect_group_item_ids(guide) != shown {
        return Err(Error::new(
            "Steam build items differ from the complete variant pools",
        ));
    }
    Ok(())
}
