use std::fmt::Write;

use deadlock_data::Result;
use serde_json::{Value, json};

use crate::presentation::{BuildPresentation, PresentationCategory};

#[must_use]
pub fn serialize_presentation(presentation: &BuildPresentation) -> Value {
    let content = presentation.content();
    let categories = content.categories.iter().map(|category| json!({
        "name":category.name,"description":category.description,"optional":category.optional,
        "width":category.width,"height":category.height,"items":category.items.iter().map(|item| json!({
            "item_id":item.item_id,"name":item.name,"annotation":item.annotation,
            "required_flex_slots":item.required_flex_slots,"sell_priority":item.sell_priority,
            "imbue_target_ability_id":item.imbue_target_ability_id})).collect::<Vec<_>>()
    })).collect::<Vec<_>>();
    json!({"schema_version":1,"hero_id":content.hero_id,"name":content.name,
        "description":content.description,"tag_ids":content.tag_ids,"categories":categories,
        "ability_order":content.abilities.as_ref().map(|ability| ability.ability_ids.as_slice()).unwrap_or_default(),
        "ability_annotation":content.abilities.as_ref().map(|ability| &ability.annotation)})
}

/// # Errors
/// Returns an error when output formatting fails.
pub fn render_presentation_markdown(presentation: &BuildPresentation) -> Result<String> {
    let content = presentation.content();
    let mut output = format!(
        "# {}\n\nSteam build content. Panels and items follow serialization order.\nThe client controls panel placement. Dimensions use native layout units.\nHero ID: {}. Tags: {}.\n\n",
        content.name,
        content.hero_id,
        content.tag_ids.map(|id| id.to_string()).join(", ")
    );
    for category in &content.categories {
        render_category(&mut output, category)?;
    }
    output.push_str("## Ability order\n\n");
    if let Some(abilities) = &content.abilities {
        writeln!(
            output,
            "{}\n\nFirst ability note:\n",
            abilities
                .ability_ids
                .iter()
                .map(u64::to_string)
                .collect::<Vec<_>>()
                .join(" → ")
        )?;
        write_indented(&mut output, &abilities.annotation, "    ")?;
    } else {
        output.push_str("No ability order.\n\n");
    }
    output.push_str("## Build description\n\n");
    write_indented(&mut output, &content.description, "    ")?;
    Ok(output)
}

fn render_category(output: &mut String, category: &PresentationCategory) -> Result<()> {
    writeln!(
        output,
        "## {}\n\nOptional: {}. Size: {} x {}.\n",
        category.name,
        if category.optional { "yes" } else { "no" },
        category.width,
        category.height
    )?;
    if !category.description.is_empty() {
        write_indented(output, &category.description, "    ")?;
    }
    if category.items.is_empty() {
        output.push_str("No items.\n\n");
    }
    for (index, item) in category.items.iter().enumerate() {
        writeln!(
            output,
            "{}. **{}** (ID {})\n",
            index + 1,
            item.name,
            item.item_id
        )?;
        write_indented(output, &item.annotation, "        ")?;
        for (label, value) in [
            (
                "Required flex slots",
                item.required_flex_slots.map(u64::from),
            ),
            ("Sell priority", item.sell_priority.map(u64::from)),
            ("Imbue ability ID", item.imbue_target_ability_id),
        ] {
            if let Some(value) = value {
                writeln!(output, "    {label}: {value}.\n")?;
            }
        }
    }
    Ok(())
}

fn write_indented(output: &mut String, value: &str, indentation: &str) -> Result<()> {
    for line in value.lines() {
        writeln!(
            output,
            "{}{line}",
            if line.is_empty() { "" } else { indentation }
        )?;
    }
    output.push('\n');
    Ok(())
}
