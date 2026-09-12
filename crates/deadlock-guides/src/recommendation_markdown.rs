use std::fmt::Write;

use deadlock_data::Result;
use serde_json::Value;

use crate::recommendation_types::{Recommendation, RecommendationAction};

/// # Errors
/// Returns an error when output formatting fails.
pub fn render_recommendation_markdown(recommendation: &Recommendation) -> Result<String> {
    let action = match recommendation.action {
        RecommendationAction::Buy => "BUY",
        RecommendationAction::Save => "SAVE",
        RecommendationAction::End => "END",
        RecommendationAction::Abstain => "ABSTAIN",
    };
    let mut output = format!("# {action}\n\n{}\n", recommendation.reason);
    let Some(plan) = &recommendation.purchase_plan else {
        return Ok(output);
    };
    writeln!(
        output,
        "\nBuild: {}\n\nCash shortfall: {} souls\n\nRemaining cost: {} souls",
        plan["path_id"]
            .as_str()
            .unwrap_or(&recommendation.policy_id),
        plan["cash_shortfall"].as_u64().unwrap_or(0),
        plan["remaining_cost"].as_u64().unwrap_or(0)
    )?;
    if let Some(steps) = plan["remaining_route"].as_array() {
        output.push_str("\n## Remaining purchases\n\n");
        for (index, step) in steps.iter().enumerate() {
            writeln!(
                output,
                "{}. {}: {} souls",
                index + 1,
                step["name"].as_str().unwrap_or("Unknown item"),
                step["incremental_cost"]
            )?;
        }
    }
    if let Some(choices) = plan["available_choices"]
        .as_array()
        .filter(|choices| !choices.is_empty())
    {
        output.push_str("\n## Available choices\n\n");
        for choice in choices {
            write_choice(&mut output, choice)?;
        }
    }
    Ok(output)
}

fn write_choice(output: &mut String, choice: &Value) -> Result<()> {
    writeln!(
        output,
        "- {}: {}",
        choice["name"].as_str().unwrap_or("Unknown item"),
        choice["instruction"].as_str().unwrap_or("")
    )?;
    if let Some(cost) = choice["extra_remaining_cost"].as_i64() {
        writeln!(output, "  Additional cost: {cost} souls.")?;
    }
    if let Some(reason) = choice["current_blocked_reason"].as_str() {
        writeln!(output, "  Blocked: {reason}")?;
    }
    Ok(())
}
