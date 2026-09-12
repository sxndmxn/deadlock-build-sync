use std::collections::BTreeMap;
use std::fmt::Write;
use std::path::Path;

use deadlock_data::{Result, atomic_write, atomic_write_json, sha256};
use deadlock_guides::{
    BuildPresentation, PurchaseGuide, build_group_record, build_presentation,
    render_presentation_markdown, render_purchase_markdown, serialize_presentation,
};
use serde_json::{Value, json};

use crate::generation_types::GeneratedGuides;

pub fn presentation(
    guide: &PurchaseGuide,
    generated: &GeneratedGuides,
) -> Result<BuildPresentation> {
    build_presentation(
        guide,
        &generated.persona,
        &generated.patch.title,
        &generated.patch.published_at,
        generated.rank_range,
    )
}

pub fn describe_guide(guide: &PurchaseGuide, generated: &GeneratedGuides) -> Result<Value> {
    Ok(
        json!({"hero_id":guide.hero_id,"hero":guide.hero_name,"path_id":guide.path_id,
        "path_label":guide.path_label,"policy_id":guide.policy_id,"snapshot_id":guide.snapshot_id,
        "summary":guide.summary,"steam_build":serialize_presentation(&presentation(guide, generated)?),
        "purchase_guidance":guide.purchase_guidance,"guide_group":build_group_record(guide)?}),
    )
}

pub fn write_build_guides(
    staged: &Path,
    destination: &Path,
    guides: &[PurchaseGuide],
    generated: &GeneratedGuides,
) -> Result<()> {
    let relative = Path::new("builds").join(generated.manifest.identifier());
    let output = staged.join(&relative);
    let mut index = "# Builds\n\n".to_owned();
    let mut entries = Vec::new();
    for guide in guides {
        let stem = format!(
            "{}-{}",
            guide.hero_id,
            &sha256(guide.path_id.as_bytes())[..16]
        );
        let presentation = presentation(guide, generated)?;
        let content = serialize_presentation(&presentation);
        atomic_write(
            &output.join(format!("{stem}.md")),
            render_presentation_markdown(&presentation)?.as_bytes(),
        )?;
        atomic_write_json(&output.join(format!("{stem}.steam.json")), &content)?;
        atomic_write(
            &output.join(format!("{stem}.details.md")),
            render_purchase_markdown(guide, true)?.as_bytes(),
        )?;
        entries.push(build_entry(guide, &stem, &content)?);
        writeln!(
            index,
            "- [{} — {}]({stem}.md)",
            guide.hero_name, guide.path_label
        )?;
    }
    atomic_write_json(
        &output.join("guides.json"),
        &json!({"schema_version":2,"snapshot_manifest":generated.manifest.to_document()?,"guides":entries}),
    )?;
    atomic_write(&output.join("INDEX.md"), index.as_bytes())?;
    for entry in &mut entries {
        if let Some(fields) = entry.as_object_mut() {
            fields.remove("purchase_guidance");
            fields.remove("guide_group");
        }
    }
    atomic_write_json(
        &staged.join("builds.json"),
        &json!({"schema_version":2,"snapshot_id":generated.manifest.identifier(),
        "directory":destination.join(relative),"guides":entries}),
    )
}

fn build_entry(guide: &PurchaseGuide, stem: &str, content: &Value) -> Result<Value> {
    Ok(
        json!({"hero_id":guide.hero_id,"hero":guide.hero_name,"path_id":guide.path_id,"policy_id":guide.policy_id,
        "markdown":format!("{stem}.md"),"steam_json":format!("{stem}.steam.json"),"steam_categories":content["categories"],"steam_build":content,
        "purchase_guidance":guide.purchase_guidance,"guide_group":build_group_record(guide)?,
        "variant_path_ids":std::iter::once(guide).chain(&guide.variant_guides).map(|guide| &guide.path_id).collect::<Vec<_>>(),
        "item_pool":guide.tiers.iter().map(|(tier, items)| (tier.to_string(), items.iter().map(|item| item.item_id).collect::<Vec<_>>())).collect::<BTreeMap<_, _>>()}),
    )
}
