use deadlock_data::{RankRange, Result};

use crate::build_title::format_date;
use crate::guide_category::GuideCategory;
use crate::guide_item::format_integer;
use crate::presentation::MANAGED_MARKER;
use crate::purchase_guide::PurchaseGuide;
use crate::purchase_instructions::format_choice_instruction;
use crate::variant_items::group_members;

pub fn build_description(
    guide: &PurchaseGuide,
    categories: &[GuideCategory],
    patch_title: &str,
    patch_published_at: &str,
    ranks: RankRange,
) -> Result<String> {
    let queue = if guide.match_mode.is_empty() {
        "Unresolved".into()
    } else {
        format_title_case(&guide.match_mode)
    };
    let ranks = if guide.rank_identity.is_empty() {
        ranks.label()
    } else {
        guide.rank_identity.clone()
    };
    let version = guide
        .client_version
        .filter(|version| *version > 0)
        .map_or_else(|| "UNRESOLVED".into(), |version| version.to_string());
    let mut lines = vec![
        format!(
            "{queue} • {ranks} • data through {} • client {version}.",
            format_date(guide.as_of_timestamp, false)?
        ),
        describe_queue_rules(guide, categories).into(),
        "Buy the selected path in the listed order. Keep its optional items with that path.".into(),
    ];
    if !guide.variant_guides.is_empty() {
        lines.extend([
            "Buy ALT CORE first. Then buy one complete VARIANT in its listed order. This path replaces MAIN CORE.".into(),
            "ALT CORE tooltips show VARIANT 1 statistics.".into(),
        ]);
    }
    if categories.iter().any(|category| category.compact) {
        lines.extend(describe_group_purchases(guide)?);
    }
    if let Some(path) = &guide.ability_path {
        let scope = if !path.filter_item_ids.is_empty() {
            "item-filtered observed"
        } else if guide.path_id != "default" {
            "shared hero-wide observed"
        } else {
            "state-composed observed"
        };
        lines.push(format!(
            "Ability order: {scope} default • tail support n={}.",
            format_integer(i128::from(path.matches))
        ));
    }
    lines.extend([
        String::new(),
        MANAGED_MARKER.into(),
        format!("Build path: {}.", guide.path_id),
        format!("Patch: {patch_title} ({patch_published_at})."),
        format!(
            "Snapshot: {}.",
            identifier_or_placeholder(&guide.snapshot_id)
        ),
        format!("Policy: {}.", identifier_or_placeholder(&guide.policy_id)),
    ]);
    Ok(lines.join("\n"))
}

const fn identifier_or_placeholder(value: &str) -> &str {
    if value.is_empty() {
        "UNRESOLVED"
    } else {
        value
    }
}

fn describe_queue_rules(guide: &PurchaseGuide, categories: &[GuideCategory]) -> &'static str {
    if categories.iter().any(|category| category.compact) {
        "Queue follows MAIN CORE only. All other panels are optional."
    } else if guide.purchase_guidance.is_some() {
        "AUTO: CORE steps only. OPTIONAL, PICK ONE, UPGRADE, and OPTIONAL ITEMS rows stay optional."
    } else if guide.optional_core_items.is_empty() {
        "AUTO: CORE left→right. TIER 1–4 never auto-queue."
    } else {
        "AUTO: CORE left→right. OPTIONAL CORE and TIER 1–4 never auto-queue."
    }
}

fn describe_group_purchases(guide: &PurchaseGuide) -> Result<Vec<String>> {
    let mut lines = Vec::new();
    for (index, member) in group_members(guide).enumerate() {
        lines.push(if index == 0 {
            "MAIN CORE purchases:".into()
        } else {
            format!("VARIANT {index} complete purchases:")
        });
        lines.push(format!(
            "Core cost: {} souls.",
            format_integer(i128::from(member.core_target_cost))
        ));
        let counts = [
            ("discovery", "discovery_owners"),
            ("selection", "selection_owners"),
            ("validation", "validation_owners"),
        ]
        .into_iter()
        .filter_map(|(label, field)| {
            member.evidence_summary[field]
                .as_u64()
                .map(|count| format!("{label} n={}", format_integer(i128::from(count))))
        })
        .collect::<Vec<_>>();
        if !counts.is_empty() {
            lines.push(format!("Observed core owners: {}.", counts.join("; ")));
        }
        lines.extend(describe_purchase_details(member)?);
    }
    Ok(lines)
}

fn describe_purchase_details(guide: &PurchaseGuide) -> Result<Vec<String>> {
    let Some(guidance) = &guide.purchase_guidance else {
        return Ok(Vec::new());
    };
    let mut lines = Vec::new();
    lines.extend(guidance.default_path.actions.iter().map(|step| {
        format!(
            "{}: +{} souls; total {}. Consumed components: {:?}.",
            step.name,
            format_integer(i128::from(step.incremental_cost)),
            format_integer(i128::from(step.cumulative_cost)),
            step.consumed_items
        )
    }));
    for card in &guidance.choices {
        lines.push(format!(
            "{}: {}",
            card.name,
            format_choice_instruction(guidance, card)?
        ));
    }
    lines.extend(guide.core_alternatives.iter().map(|row| {
        let row = row.content();
        format!("{} {}. {} {}", row.when, row.swap, row.why, row.skip)
    }));
    Ok(lines)
}

fn format_title_case(value: &str) -> String {
    let mut start = true;
    let mut result = String::new();
    for character in value.chars() {
        if start {
            result.extend(character.to_uppercase());
        } else {
            result.extend(character.to_lowercase());
        }
        start = !character.is_alphabetic();
    }
    result
}
