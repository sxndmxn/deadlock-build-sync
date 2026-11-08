use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Error, Result, integer, text};
use serde_json::Value;

const AXIS_CLASSES: [&str; 3] = [
    "citadel_build_tag_weapon",
    "citadel_build_tag_spirit",
    "citadel_build_tag_vitality",
];
/// The function tags, in the order of `classify_function` in `build_tags.rs`.
pub const FUNCTION_CLASSES: [&str; 8] = [
    "citadel_build_tag_damage",
    "citadel_build_tag_utility",
    "citadel_build_tag_healing",
    "citadel_build_tag_crowd_control",
    "citadel_build_tag_mobility",
    "citadel_build_tag_melee",
    "citadel_build_tag_headshots",
    "citadel_build_tag_debuff",
];
const COMPLEXITY_CLASSES: [&str; 3] = [
    "citadel_build_tag_complexity_1",
    "citadel_build_tag_complexity_2",
    "citadel_build_tag_complexity_3",
];

/// The build tag identifier of each tag class, from the API build tag assets.
#[derive(Clone, Debug)]
pub struct BuildTagCatalog {
    tags: BTreeMap<String, u64>,
}

impl BuildTagCatalog {
    /// # Errors
    /// Returns an error when the catalog has missing, unknown, malformed, or duplicate tags.
    pub fn from_assets(assets: &[Value]) -> Result<Self> {
        let mut tags = BTreeMap::new();
        let mut ids = BTreeSet::new();
        for asset in assets {
            let class_name = text(asset, "class_name")?.trim();
            let label = text(asset, "label")?.trim();
            let tag_id = integer(asset, "id")?;
            if class_name.is_empty() || label.is_empty() || tag_id == 0 {
                return Err(Error::new("Build tag catalog contains a malformed tag"));
            }
            if tags.insert(class_name.to_owned(), tag_id).is_some() || !ids.insert(tag_id) {
                return Err(Error::new(
                    "Build tag catalog repeats a class or identifier",
                ));
            }
        }
        let expected = AXIS_CLASSES
            .into_iter()
            .chain(FUNCTION_CLASSES)
            .chain(COMPLEXITY_CLASSES)
            .map(str::to_owned)
            .collect::<BTreeSet<_>>();
        if tags.keys().cloned().collect::<BTreeSet<_>>() != expected {
            return Err(Error::new(
                "Build tag catalog must contain exactly the 14 supported tags",
            ));
        }
        Ok(Self { tags })
    }

    /// Returns the tag identifier of a class.
    ///
    /// # Errors
    /// Returns an error when the catalog does not contain the specified class.
    pub fn require(&self, class_name: &str) -> Result<u64> {
        self.tags
            .get(class_name)
            .copied()
            .ok_or_else(|| Error::new(format!("Missing build tag: {class_name}")))
    }
}
