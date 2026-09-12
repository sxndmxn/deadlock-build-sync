use deadlock_data::{Error, Result, integer};
use deadlock_guides::{HeroEvidence, PurchaseGuide, parse_ability_definitions, select_hero_build};
use deadlock_input::build_hero_mechanics;
use serde_json::{Value, json};

use crate::discovery_models::ExportContext;

pub fn validate_complete_guide(
    build: &mut Value,
    hero: &Value,
    cohort: &Value,
    context: &ExportContext,
    group: &str,
) -> Result<()> {
    build["guide_group_id"] = group.into();
    let record =
        json!({"hero_id":integer(hero,"id")?,"hero":hero["name"],"cohort":cohort,"builds":[build]});
    let evidence = HeroEvidence::from_document(&record)?;
    let build = evidence
        .builds
        .first()
        .ok_or_else(|| Error::new("Beam guide has no build evidence"))?;
    let selected = select_hero_build(build, &context.normal_assets)?;
    let definitions =
        parse_ability_definitions(&build_hero_mechanics(hero, &context.normal_assets)?)?;
    for item in selected
        .core
        .iter()
        .chain(&selected.core_purchase_path)
        .chain(&selected.optional_core)
        .chain(selected.tiers.values().flatten())
    {
        if let Some(target) = item.content().imbue_target_ability_id
            && !definitions.contains_key(&target)
        {
            return Err(Error::new(format!(
                "Item {} has an imbue target outside the current hero abilities",
                item.content().item
            )));
        }
    }
    if !PurchaseGuide::from_selected(hero, &selected, None)?.has_complete_item_coverage() {
        return Err(Error::new(
            "Beam guide lacks supported item coverage in every tier",
        ));
    }
    Ok(())
}
