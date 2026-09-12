use std::fmt::Write;

use deadlock_data::{Error, Result};

use crate::guide_groups::{VARIANT_RULE, describe_variant_changes};
use crate::purchase_guidance_types::PurchaseGuidance;
use crate::purchase_guide::PurchaseGuide;
use crate::purchase_instructions::format_choice_instruction;

/// # Errors
/// Returns an error when guidance is missing, choice instructions are invalid, or output formatting fails.
pub fn render_purchase_markdown(guide: &PurchaseGuide, details: bool) -> Result<String> {
    let guidance = guide
        .purchase_guidance
        .as_ref()
        .ok_or_else(|| Error::new("Build has no purchase guidance"))?;
    let mut output = format!(
        "# {} — {}\n\nBuild: `{}`. Core: {} souls.\nRanks: {}. Evidence: {}.\n\n",
        guide.hero_name,
        guide.build_archetype,
        guide.path_id,
        guidance.default_path.remaining_cost,
        guide.rank_identity,
        guidance
            .evidence
            .get("status")
            .and_then(serde_json::Value::as_str)
            .unwrap_or("observed")
    );
    output.push_str("Follow the core unless you need an optional effect. PICK ONE identifies the next purchase for that need.\n\nCore prices are incremental. Optional cost includes components and rebuys. An upgrade consumes its component and credits its cost.\n\n");
    render_variants(&mut output, guide)?;
    if let Some(ability) = &guide.ability_path {
        writeln!(output, "## Ability order\n\n{}\n", ability.annotation())?;
    }
    render_route(&mut output, guidance)?;
    render_substitutions(&mut output, guide, guidance)?;
    output.push_str("## Item pool\n\nThese tiers contain the full item pool. Tier order does not specify purchase order.\n\n");
    for tier in 1..=4 {
        let names = guide
            .tiers
            .get(&tier)
            .map(|items| {
                items
                    .iter()
                    .map(|item| item.name.as_str())
                    .collect::<Vec<_>>()
                    .join(", ")
            })
            .unwrap_or_default();
        writeln!(
            output,
            "- **Tier {tier}:** {}.",
            if names.is_empty() {
                "No supported options are available"
            } else {
                &names
            }
        )?;
    }
    if details {
        render_details(&mut output, guidance)?;
    }
    writeln!(
        output,
        "\nEach choice preserves the core upgrade paths. Recalculate from actual inventory when you combine choices. Slot and active item limits apply.\n\n{}. Automatic choices require admitted branch evidence.\n",
        guidance.evidence_basis
    )?;
    if details {
        for variant in &guide.variant_guides {
            output.push_str(&render_purchase_markdown(variant, true)?);
        }
    }
    Ok(output)
}

fn render_route(output: &mut String, guidance: &PurchaseGuidance) -> Result<()> {
    output.push_str("## Purchase path and choices\n\n");
    for index in 0..=guidance.default_path.actions.len() {
        if let Some(step) = index
            .checked_sub(1)
            .and_then(|position| guidance.default_path.actions.get(position))
        {
            writeln!(
                output,
                "**{index}. {} — {} souls**\n",
                step.name, step.incremental_cost
            )?;
        }
        for decision in guidance
            .decisions
            .iter()
            .filter(|decision| decision.after_step == index)
        {
            writeln!(output, "**{} — {}**\n", decision.kind, decision.purpose)?;
            for id in &decision.options {
                let card = guidance
                    .choices
                    .iter()
                    .find(|card| card.item_id == *id)
                    .ok_or_else(|| Error::new("Purchase decision references an unknown choice"))?;
                writeln!(
                    output,
                    "- **{}:** {}",
                    card.name,
                    format_choice_instruction(guidance, card)?
                )?;
            }
            output.push('\n');
        }
    }
    for card in guidance
        .choices
        .iter()
        .filter(|card| card.after_step.is_none() || card.blocked_reason.is_some())
    {
        writeln!(
            output,
            "- **{}:** {}",
            card.name,
            format_choice_instruction(guidance, card)?
        )?;
    }
    Ok(())
}

fn render_variants(output: &mut String, guide: &PurchaseGuide) -> Result<()> {
    if !guide.variant_guides.is_empty() {
        writeln!(output, "## Core variants\n\n{VARIANT_RULE}\n")?;
        for (index, variant) in guide.variant_guides.iter().enumerate() {
            writeln!(
                output,
                "- **Variant {}:** {}. {} souls.",
                index + 1,
                describe_variant_changes(guide, variant),
                variant.core_target_cost
            )?;
        }
        output.push('\n');
    }
    Ok(())
}

fn render_substitutions(
    output: &mut String,
    guide: &PurchaseGuide,
    guidance: &PurchaseGuidance,
) -> Result<()> {
    if !guide.core_alternatives.is_empty() {
        output.push_str("## Optional core substitutions\n\n");
        for alternative in &guide.core_alternatives {
            let alternative = alternative.content();
            writeln!(
                output,
                "- **{}** replaces **{}**. {} {}",
                item_name(guidance, alternative.item_id)?,
                item_name(guidance, alternative.comparator_item_id)?,
                alternative.when,
                alternative.skip
            )?;
        }
        output.push('\n');
    }
    Ok(())
}

fn render_details(output: &mut String, guidance: &PurchaseGuidance) -> Result<()> {
    output.push_str("\n## Choice details\n\n");
    for card in &guidance.choices {
        writeln!(
            output,
            "### {}\n\n{}\nTiming: {}.\nMechanic source: {}; {}.\n",
            card.name,
            format_choice_instruction(guidance, card)?,
            card.timing_basis,
            card.purpose.basis,
            card.purpose.evidence
        )?;
        if let Some(plan) = &card.plan {
            writeln!(
                output,
                "Path: {}.\nEnding inventory: {}.\nRemaining cost: {} souls.\n",
                route_names(guidance, plan.actions.iter().map(|step| step.item_id))?,
                route_names(guidance, plan.final_inventory.iter().copied())?,
                plan.remaining_cost
            )?;
        }
    }
    writeln!(output, "Evidence: {}\n", guidance.evidence)?;
    Ok(())
}

fn route_names(guidance: &PurchaseGuidance, ids: impl Iterator<Item = u64>) -> Result<String> {
    ids.map(|id| item_name(guidance, id))
        .collect::<Result<Vec<_>>>()
        .map(|names| names.join(" → "))
}

fn item_name(guidance: &PurchaseGuidance, id: u64) -> Result<&str> {
    guidance
        .names
        .get(&id)
        .map(String::as_str)
        .ok_or_else(|| Error::new("Purchase guidance has no item name"))
}
