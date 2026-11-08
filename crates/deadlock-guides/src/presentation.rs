use deadlock_data::{Error, Result};

use crate::ability_order::is_complete_ability_order;
use crate::build_text::{MAIN_CORE_PANEL, tier_panel_name};
use crate::build_title::MAX_BUILD_NAME_CHARACTERS;
use crate::hero_build::CounterTarget;

/// The game shows at most this many UTF-8 bytes of a category description or an item annotation.
const MAXIMUM_TEXT_BYTES: usize = 240;

pub const MANAGED_MARKER: &str = "[deadlock-build-sync:v2]";
pub const LEGACY_MANAGED_MARKER: &str = "[deadlock-build-sync:v1]";

/// The lines at the end of a managed build description that identify the build to this tool.
///
/// Production renders them, and the Steam installer parses them to find the builds that it
/// manages. One definition keeps the two sides equal.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ManagedTrailer {
    /// The build path `HERO_ID-VARIANT`, the stable identity of the build in Steam.
    pub path_id: String,
    pub patch_title: String,
    pub snapshot_id: String,
}

impl ManagedTrailer {
    #[must_use]
    pub fn render(&self) -> String {
        format!(
            "{MANAGED_MARKER}\nBuild path: {}.\nPatch: {}.\nSnapshot: {}.",
            self.path_id, self.patch_title, self.snapshot_id
        )
    }

    /// Parses the trailer of a description with the current marker.
    ///
    /// A description with the legacy marker, or without a valid build path, gives `None`.
    #[must_use]
    pub fn parse(description: &str) -> Option<Self> {
        if !description.contains(MANAGED_MARKER) {
            return None;
        }
        let line = |prefix: &str| {
            description
                .split('\n')
                .find_map(|line| line.strip_prefix(prefix)?.strip_suffix('.'))
        };
        let path_id = line("Build path: ").filter(|path| is_build_path(path))?;
        Some(Self {
            path_id: path_id.into(),
            patch_title: line("Patch: ").unwrap_or_default().into(),
            snapshot_id: line("Snapshot: ").unwrap_or_default().into(),
        })
    }

    /// Returns true when the description has the current or the legacy marker.
    #[must_use]
    pub fn is_marked(description: &str) -> bool {
        description.contains(MANAGED_MARKER) || description.contains(LEGACY_MANAGED_MARKER)
    }
}

/// A build path or variant has lowercase letters, digits, and hyphens.
#[must_use]
pub fn is_build_path(path: &str) -> bool {
    !path.is_empty()
        && path
            .bytes()
            .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'-')
}

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
            || content.name.chars().count() > MAX_BUILD_NAME_CHARACTERS
        {
            return Err(Error::new(
                "Build requires a positive hero ID and a name with 1 to 50 characters",
            ));
        }
        let tags = content.tag_ids;
        if tags.contains(&0) || tags[0] == tags[1] || tags[0] == tags[2] || tags[1] == tags[2] {
            return Err(Error::new("Build requires three distinct positive tags"));
        }
        if ManagedTrailer::parse(&content.description).is_none() {
            return Err(Error::new(
                "Build description has no managed marker with a valid build path",
            ));
        }
        validate_panel_order(&content.categories)?;
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

/// The optional counter panels between MAIN CORE and the tiers, in their required order.
const COUNTER_PANELS: [&str; 3] = [
    CounterTarget::Weapon.panel_name(),
    CounterTarget::Spirit.panel_name(),
    CounterTarget::Sustain.panel_name(),
];

fn validate_panel_order(categories: &[PresentationCategory]) -> Result<()> {
    let counters = categories.len().saturating_sub(5);
    let mut counter_names = COUNTER_PANELS.iter();
    let counters_in_order = categories
        .iter()
        .skip(1)
        .take(counters)
        .all(|category| counter_names.any(|name| category.name == *name));
    let tiers_in_order = categories
        .iter()
        .skip(1 + counters)
        .map(|category| category.name.clone())
        .eq((1..=4).map(tier_panel_name));
    if categories.len() < 5
        || categories.len() > 5 + COUNTER_PANELS.len()
        || categories[0].name != MAIN_CORE_PANEL
        || !counters_in_order
        || !tiers_in_order
        || categories.iter().enumerate().any(|(index, category)| {
            category.optional != (index > 0) || (index <= counters && category.items.is_empty())
        })
    {
        return Err(Error::new(
            "Build requires MAIN CORE, optional VS WEAPON, VS SPIRIT, and VS SUSTAIN panels in this order, and four optional tiers",
        ));
    }
    Ok(())
}

fn validate_category(category: &PresentationCategory) -> Result<()> {
    if category.name.trim().is_empty() || category.description.len() > MAXIMUM_TEXT_BYTES {
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
        if item.item_id == 0 || item.annotation.len() > MAXIMUM_TEXT_BYTES {
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
    if !is_complete_ability_order(&abilities.ability_ids) {
        return Err(Error::new(
            "Ability order must contain four purchases for each of four abilities",
        ));
    }
    Ok(())
}
