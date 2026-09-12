use deadlock_data::{Error, RankRange, Result};

use crate::build_description::build_description;
use crate::build_title::{format_build_name, format_date};
use crate::presentation::{
    BuildPresentation, PresentationAbilities, PresentationCategory, PresentationContent,
    PresentationItem,
};
use crate::purchase_guide::PurchaseGuide;
use crate::variant_categories::validate_group_categories;

/// # Errors
/// Returns an error when the guide has invalid variants, tags, dates, title, category text, or item annotations.
pub fn build_presentation(
    guide: &PurchaseGuide,
    persona: &str,
    patch_title: &str,
    patch_published_at: &str,
    ranks: RankRange,
) -> Result<BuildPresentation> {
    ranks.validate()?;
    validate_group_categories(guide)?;
    let categories = guide.rendered_categories()?;
    let tag_ids: [u64; 3] = guide
        .build_tag_ids
        .clone()
        .try_into()
        .map_err(|_| Error::new("Guide does not have exactly three build tags"))?;
    let window = format!(
        "{}–{}",
        format_date(guide.analysis_start_timestamp, true)?,
        format_date(guide.as_of_timestamp, true)?
    );
    let content = PresentationContent {
        hero_id: guide.hero_id,
        name: format_build_name(persona, &guide.build_archetype, patch_title, &window)?,
        tag_ids,
        description: build_description(guide, &categories, patch_title, patch_published_at, ranks)?,
        categories: categories
            .iter()
            .map(|category| PresentationCategory {
                name: category.name.clone(),
                description: category.description.clone(),
                width: category.width,
                height: category.height,
                optional: category.optional,
                items: category
                    .items
                    .iter()
                    .map(|item| PresentationItem {
                        item_id: item.item_id,
                        name: item.name.clone(),
                        annotation: item.annotation(),
                        required_flex_slots: item.required_flex_slots,
                        sell_priority: item.sell_priority,
                        imbue_target_ability_id: item.imbue_target_ability_id,
                    })
                    .collect(),
            })
            .collect(),
        abilities: guide
            .ability_path
            .as_ref()
            .map(|path| PresentationAbilities {
                ability_ids: path.ability_ids.clone(),
                annotation: path.annotation(),
            }),
    };
    BuildPresentation::new(content)
}
