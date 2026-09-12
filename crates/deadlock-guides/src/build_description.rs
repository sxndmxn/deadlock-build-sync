use std::fmt::Write as _;

use deadlock_data::{RankRange, Result};
use serde_json::Value;

use crate::beam_display::{variant_state_labels, variant_statistics};
use crate::build_title::format_date;
use crate::guide_category::GuideCategory;
use crate::guide_groups::describe_variant_changes;
use crate::guide_item::format_integer;
use crate::presentation::MANAGED_MARKER;
use crate::purchase_guide::PurchaseGuide;
use crate::purchase_instructions::format_choice_instruction;

pub fn build_description(
    guide: &PurchaseGuide,
    categories: &[GuideCategory],
    patch_title: &str,
    patch_published_at: &str,
    ranks: RankRange,
) -> Result<String> {
    let (role, plan) = guide.tactical_profile.as_ref().map_or_else(
        || {
            let role = if guide.summary.is_empty() {
                format!("Evidence-grounded default for {}.", guide.hero_name)
            } else {
                guide.summary.clone()
            };
            (
                role,
                "Use observed order as a default and deviate when the match requires.".into(),
            )
        },
        |profile| {
            (
                format!("{}: {}", profile.primary_role, profile.fight_role),
                profile.economy_plan.clone(),
            )
        },
    );
    let queue = if guide.match_mode.is_empty() {
        "Unresolved".into()
    } else {
        title_case(&guide.match_mode)
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
        role,
        queue_rule(guide, categories).into(),
        plan,
        format!(
            "{queue} • {ranks} • data through {} • client {version}.",
            format_date(guide.as_of_timestamp, false)?
        ),
    ];
    if guide
        .evidence_summary
        .as_object()
        .is_some_and(|fields| !fields.is_empty())
    {
        lines.push(format!(
            "Evidence: {}. Timing: {}.",
            deadlock_data::text(&guide.evidence_summary, "status")?,
            deadlock_data::text(&guide.evidence_summary, "timing_status")?
        ));
        lines.push(format!(
            "Evidence limits: {}.",
            python_display(&guide.evidence_summary["limitations"])
        ));
    }
    let statistics = variant_statistics(guide, true)?;
    if !statistics.is_empty() {
        lines.extend([format!("Default core: {}", statistics.join(" ")),
            "Rates describe validation matches with the complete core. Variant samples can overlap.".into(),
            "Wealth states compare personal net worth with the lobby average. Behind: below 90%. Even: 90% through 110%. Ahead: above 110%.".into()]);
    }
    lines.extend(describe_variants(guide, categories)?);
    if categories.iter().any(|category| category.compact) {
        lines.extend(describe_purchase_details(guide)?);
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
        "Private evidence-grounded guide generated from deadlock-api.com.".into(),
        format!("Patch: {patch_title} ({patch_published_at})."),
        format!("Snapshot: {}.", resolved(&guide.snapshot_id)),
        format!("Policy: {}.", resolved(&guide.policy_id)),
        "Claim limit: observational; no causal item effect.".into(),
    ]);
    Ok(lines.join("\n"))
}

const fn resolved(value: &str) -> &str {
    if value.is_empty() {
        "UNRESOLVED"
    } else {
        value
    }
}

fn queue_rule(guide: &PurchaseGuide, categories: &[GuideCategory]) -> &'static str {
    if categories.iter().any(|category| category.compact) {
        "Queue follows CORE ITEMS only. All other panels are optional."
    } else if guide.purchase_guidance.is_some() {
        "AUTO: CORE steps only. OPTIONAL, PICK ONE, UPGRADE, and ITEM POOL rows stay optional."
    } else if guide.optional_core_items.is_empty() {
        "AUTO: CORE left→right. TIER 1–4 never auto-queue."
    } else {
        "AUTO: CORE left→right. OPTIONAL CORE and TIER 1–4 never auto-queue."
    }
}

fn describe_variants(guide: &PurchaseGuide, categories: &[GuideCategory]) -> Result<Vec<String>> {
    if guide.variant_guides.is_empty() {
        return Ok(Vec::new());
    }
    let mut lines = vec![format!("{} alternative variants. CORE ITEMS contains the complete default purchase path. V numbers identify the full variant paths below.", guide.variant_guides.len()),
        if categories.iter().any(|category| category.name == "ALTERNATIVE CORE") {
            "ALTERNATIVE CORE contains common final items. Combine it with one panel marked ALTERNATIVE CORE +. Each complete variant replaces CORE ITEMS. Follow that variant's complete purchase order. Shared and variant items can occur at different steps."
        } else { "Each VARIANT panel contains its complete final core. Follow that variant's complete purchase order." }.into(),
        "Variant notes show recorded wealth states and complete-core win rates. State labels describe observed matches. They do not establish when to change a partly purchased core.".into()];
    for (index, variant) in guide.variant_guides.iter().enumerate() {
        let order = variant
            .core_purchase_items
            .iter()
            .map(|item| {
                item.imbue_target_ability.as_ref().map_or_else(
                    || item.name.clone(),
                    |target| format!("{} [imbue {target}]", item.name),
                )
            })
            .collect::<Vec<_>>()
            .join(" -> ");
        let mut alternatives = String::new();
        for row in &variant.core_alternatives {
            let row = row.content();
            write!(
                alternatives,
                " Conditional core: {} {}. {} {}",
                row.when, row.swap, row.why, row.skip
            )?;
        }
        lines.push(format!(
            "V{} ({}): {}. {} souls; {}. {} Order: {order}{alternatives}",
            index + 1,
            variant_state_labels(variant),
            describe_variant_changes(guide, variant),
            format_integer(i128::from(variant.core_target_cost)),
            variant.evidence_summary["status"]
                .as_str()
                .unwrap_or("observed"),
            variant_statistics(variant, true)?.join(" ")
        ));
    }
    Ok(lines)
}

fn describe_purchase_details(guide: &PurchaseGuide) -> Result<Vec<String>> {
    let Some(guidance) = &guide.purchase_guidance else {
        return Ok(Vec::new());
    };
    let mut lines = vec!["Buy CORE ITEMS from left to right. All other sections are optional. Tier numbers show item prices. Keep the selected variant's core and pool together.".into()];
    lines.extend(guidance.default_path.actions.iter().map(|step| {
        format!(
            "{}: +{} souls; total {}.",
            step.name,
            format_integer(i128::from(step.incremental_cost)),
            format_integer(i128::from(step.cumulative_cost))
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

fn title_case(value: &str) -> String {
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

fn python_display(value: &Value) -> String {
    match value {
        Value::Array(values) => format!(
            "[{}]",
            values
                .iter()
                .map(python_display)
                .collect::<Vec<_>>()
                .join(", ")
        ),
        Value::String(value) => {
            let quote = if value.contains('\'') && !value.contains('"') {
                '"'
            } else {
                '\''
            };
            let escaped = value
                .replace('\\', "\\\\")
                .replace(quote, &format!("\\{quote}"))
                .replace('\n', "\\n")
                .replace('\r', "\\r")
                .replace('\t', "\\t");
            format!("{quote}{escaped}{quote}")
        }
        Value::Null => "None".into(),
        Value::Bool(value) => if *value { "True" } else { "False" }.into(),
        Value::Number(_) | Value::Object(_) => value.to_string(),
    }
}
