use std::collections::BTreeMap;

use deadlock_data::{Error, Result};

pub const MANAGED_MARKER: &str = "[deadlock-build-sync:v2]";
pub const LEGACY_MANAGED_MARKER: &str = "[deadlock-build-sync:v1]";

#[derive(Clone, Debug)]
pub struct PresentationItem {
    pub item_id: u64,
    pub name: String,
    pub annotation: String,
    pub required_flex_slots: Option<u32>,
    pub sell_priority: Option<u32>,
    pub imbue_target_ability_id: Option<u64>,
}

#[derive(Clone, Debug)]
pub struct PresentationCategory {
    pub name: String,
    pub items: Vec<PresentationItem>,
    pub description: String,
    pub width: f32,
    pub height: f32,
    pub optional: bool,
}

#[derive(Clone, Debug)]
pub struct PresentationAbilities {
    pub ability_ids: Vec<u64>,
    pub annotation: String,
}

#[derive(Clone, Debug)]
pub struct PresentationContent {
    pub hero_id: u64,
    pub name: String,
    pub tag_ids: [u64; 3],
    pub description: String,
    pub categories: Vec<PresentationCategory>,
    pub abilities: Option<PresentationAbilities>,
}

#[derive(Clone, Debug)]
pub struct BuildPresentation(PresentationContent);

impl BuildPresentation {
    /// # Errors
    /// Returns an error when the content violates the Steam presentation contract.
    pub fn new(content: PresentationContent) -> Result<Self> {
        if content.hero_id == 0
            || content.name.trim().is_empty()
            || content.name.chars().count() > 50
        {
            return Err(Error::new(
                "Build requires a positive hero ID and a name with 1 to 50 characters",
            ));
        }
        let tags = content.tag_ids;
        if tags.contains(&0) || tags[0] == tags[1] || tags[0] == tags[2] || tags[1] == tags[2] {
            return Err(Error::new("Build requires three distinct positive tags"));
        }
        if !content.description.contains(MANAGED_MARKER) {
            return Err(Error::new("Build description has no managed marker"));
        }
        if !content
            .categories
            .iter()
            .any(|category| !category.optional && !category.items.is_empty())
        {
            return Err(Error::new(
                "Build requires a nonempty automatic purchase category",
            ));
        }
        for category in &content.categories {
            validate_category(category)?;
        }
        if let Some(abilities) = &content.abilities {
            validate_abilities(abilities)?;
        }
        Ok(Self(content))
    }

    #[must_use]
    pub const fn content(&self) -> &PresentationContent {
        &self.0
    }
}

fn validate_category(category: &PresentationCategory) -> Result<()> {
    if category.name.trim().is_empty() || category.description.len() > 240 {
        return Err(Error::new(
            "Category requires a name and a description of at most 240 UTF-8 bytes",
        ));
    }
    if !category.width.is_finite()
        || !category.height.is_finite()
        || category.width <= 0.0
        || category.height <= 0.0
    {
        return Err(Error::new(
            "Category dimensions must be finite positive numbers",
        ));
    }
    for item in &category.items {
        if item.item_id == 0 || item.annotation.len() > 240 {
            return Err(Error::new(
                "Item requires a positive ID and an annotation of at most 240 UTF-8 bytes",
            ));
        }
        if item.required_flex_slots.is_some_and(|count| count > 3)
            || item.imbue_target_ability_id == Some(0)
        {
            return Err(Error::new(
                "Item has an invalid flex slot count or imbue ability ID",
            ));
        }
    }
    Ok(())
}

fn validate_abilities(abilities: &PresentationAbilities) -> Result<()> {
    let mut counts = BTreeMap::<u64, usize>::new();
    for ability in &abilities.ability_ids {
        *counts.entry(*ability).or_default() += 1;
    }
    if counts.len() != 4 || counts.contains_key(&0) || counts.values().any(|count| *count != 4) {
        return Err(Error::new(
            "Ability order must contain four purchases for each of four abilities",
        ));
    }
    Ok(())
}
