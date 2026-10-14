use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;

use deadlock_data::{Error, Result, atomic_write_json, count_as_f64, read_json};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

pub const HERO_BUILD_SCHEMA_VERSION: u32 = 7;
pub const HERO_BUILD_METHOD: &str = "item-effect-variants-v2";

/// All hero builds from one source snapshot.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HeroBuildCatalog {
    pub schema_version: u32,
    pub method: String,
    pub client_version: u64,
    pub patch: Map<String, Value>,
    pub cohort: BuildCohort,
    pub heroes: Vec<HeroBuild>,
}

/// The matches that the builds use.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BuildCohort {
    pub minimum_badge: u16,
    pub maximum_badge: u16,
    pub since: String,
    pub as_of: String,
    pub player_matches: u64,
}

/// One hero build: the CORE purchase order and situational items for each tier.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HeroBuild {
    pub hero_id: u64,
    pub hero_name: String,
    /// A stable variant identity. Older builds use the main variant.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub variant_id: Option<String>,
    pub title: String,
    pub tag_ids: [u64; 3],
    pub key_ability_name: Option<String>,
    pub ability_focus: Option<AbilityFocus>,
    pub core: Vec<BuildItem>,
    pub situational: Vec<BuildItem>,
    pub key_item_id: u64,
    pub power_spike_net_worth: u32,
    pub ability_ids: Vec<u64>,
    pub ability_matches: u64,
    pub evaluation: BuildEvaluation,
    pub observations: u64,
}

/// One item with the values that place it in the build.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BuildItem {
    pub item_id: u64,
    pub name: String,
    pub tier: u8,
    pub cost: u32,
    pub phase_s: u32,
    /// Phase ownership in the assembly cohort. This value controls item selection.
    pub adoption: f64,
    /// Phase owner win rate in the assembly cohort. Display rates use purchase statistics.
    pub win_rate: f64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub statistics: Option<ItemStatistics>,
    pub effect: f64,
    pub median_net_worth: u32,
    /// The lower and upper quartile of net worth at the first purchase.
    pub soul_window: [u32; 2],
    pub imbue_target: Option<ImbueTarget>,
}

/// Full hero cohort counts. Each player match counts once for each purchased item.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ItemStatistics {
    pub hero_matches: u64,
    pub buyer_matches: u64,
    pub buyer_wins: u64,
}

impl ItemStatistics {
    /// # Errors
    /// Returns an error for empty or inconsistent counts.
    pub fn validate(&self) -> Result<()> {
        if self.buyer_matches == 0
            || self.buyer_wins > self.buyer_matches
            || self.buyer_matches > self.hero_matches
        {
            return Err(Error::new("Item purchase statistics have invalid counts"));
        }
        Ok(())
    }
}

impl BuildItem {
    /// Formats buyer win rate and purchase rate with their counts.
    /// Legacy items without purchase counts have no display rates.
    ///
    /// # Errors
    /// Returns an error when purchase counts are invalid.
    pub fn describe_rates(&self) -> Result<[String; 2]> {
        let Some(statistics) = &self.statistics else {
            return Ok(["unavailable".into(), "unavailable".into()]);
        };
        statistics.validate()?;
        let format_rate = |count, total| -> Result<String> {
            let rate = 100.0 * count_as_f64(count)? / count_as_f64(total)?;
            Ok(format!("{rate:.1}% ({count}/{total})"))
        };
        Ok([
            format_rate(statistics.buyer_wins, statistics.buyer_matches)?,
            format_rate(statistics.buyer_matches, statistics.hero_matches)?,
        ])
    }
}

/// The selected native imbue target and its first-purchase evidence.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ImbueTarget {
    pub ability_id: u64,
    pub matches: u64,
    pub observations: u64,
}

/// An inferred ability focus supported by direct ability improvements in CORE.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AbilityFocus {
    pub ability_id: u64,
    pub name: String,
    pub supporting_item_ids: Vec<u64>,
}

impl AbilityFocus {
    pub(crate) fn validate(&self, build: &HeroBuild) -> Result<()> {
        let items = self.supporting_item_ids.iter().collect::<BTreeSet<_>>();
        if self.ability_id == 0
            || self.name.trim().is_empty()
            || !build.ability_ids.contains(&self.ability_id)
            || items.is_empty()
            || items.len() != self.supporting_item_ids.len()
        {
            return Err(Error::new(
                "Ability focus has an invalid identity or item list",
            ));
        }
        for item_id in &self.supporting_item_ids {
            if !build.core.iter().any(|item| {
                item.item_id == *item_id
                    && item
                        .imbue_target
                        .as_ref()
                        .is_some_and(|target| target.ability_id == self.ability_id)
            }) {
                return Err(Error::new(
                    "Ability focus lacks a matching CORE imbue target",
                ));
            }
        }
        if !self.supporting_item_ids.contains(&build.key_item_id)
            && items.len() < 2
            && crate::build_tags::first_fully_upgraded_ability(&build.ability_ids).ok()
                != Some(self.ability_id)
        {
            return Err(Error::new(
                "Ability focus lacks key item, CORE item, or ability order support",
            ));
        }
        Ok(())
    }
}

impl ImbueTarget {
    /// # Errors
    /// Returns an error unless at least 20 observations support a positive target with a strict majority.
    pub fn validate(&self) -> Result<()> {
        if self.ability_id == 0
            || self.matches < 20
            || self.matches > self.observations
            || self.matches <= self.observations / 2
        {
            return Err(Error::new(
                "Item imbue target has insufficient or invalid evidence",
            ));
        }
        Ok(())
    }
}

/// Held-out test of the build: the win association of following it in similar game states.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BuildEvaluation {
    pub agreement_coefficient: f64,
    pub standard_error: f64,
    pub observations: u64,
    pub confidence: Confidence,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Confidence {
    Strong,
    Moderate,
    Limited,
}

impl Confidence {
    /// Classifies a held-out agreement coefficient by its distance from zero.
    #[must_use]
    pub fn classify(coefficient: f64, standard_error: f64) -> Self {
        if 2.0f64.mul_add(-standard_error, coefficient) > 0.0 {
            Self::Strong
        } else if coefficient > 0.0 {
            Self::Moderate
        } else {
            Self::Limited
        }
    }

    #[must_use]
    pub const fn label(self) -> &'static str {
        match self {
            Self::Strong => "strong",
            Self::Moderate => "moderate",
            Self::Limited => "limited",
        }
    }
}

impl HeroBuild {
    /// Returns the managed Steam build identity for this hero and variant.
    #[must_use]
    pub fn path_id(&self) -> String {
        format!(
            "{}-{}",
            self.hero_id,
            self.variant_id.as_deref().unwrap_or("main")
        )
    }

    #[must_use]
    pub fn key_item(&self) -> Option<&BuildItem> {
        self.core
            .iter()
            .find(|item| item.item_id == self.key_item_id)
    }
}

impl HeroBuildCatalog {
    /// # Errors
    /// Returns an error when the file is missing, malformed, or fails validation.
    pub fn read(path: &Path) -> Result<Self> {
        let catalog: Self = serde_json::from_value(read_json(path)?)?;
        catalog.validate()?;
        Ok(catalog)
    }

    /// # Errors
    /// Returns an error when validation or the atomic write fails.
    pub fn write(&self, path: &Path) -> Result<()> {
        self.validate()?;
        atomic_write_json(path, &serde_json::to_value(self)?)
    }

    /// # Errors
    /// Returns an error for an unsupported schema or method, repeated build paths, or an invalid build.
    pub fn validate(&self) -> Result<()> {
        let current =
            self.schema_version == HERO_BUILD_SCHEMA_VERSION && self.method == HERO_BUILD_METHOD;
        let legacy = match (self.schema_version, self.method.as_str()) {
            (5, "item-effect-ridge-v1") => {
                self.heroes.iter().all(|build| build.variant_id.is_none())
            }
            (6, "item-effect-variants-v1") => true,
            _ => false,
        };
        if !current && !legacy {
            return Err(Error::new(
                "Hero builds use another schema or method. Run deadlock-build-sync sync",
            ));
        }
        if self.cohort.minimum_badge > self.cohort.maximum_badge {
            return Err(Error::new("Hero build cohort has an invalid rank range"));
        }
        let mut paths = BTreeSet::new();
        let mut names = BTreeMap::new();
        for hero in &self.heroes {
            if !paths.insert((hero.hero_id, hero.path_id())) {
                return Err(Error::new("Hero builds repeat a hero and build path pair"));
            }
            if names
                .insert(hero.hero_id, &hero.hero_name)
                .is_some_and(|name| name != &hero.hero_name)
            {
                return Err(Error::new(
                    "Build variants use different names for the same hero",
                ));
            }
            validate_hero(hero)?;
        }
        validate_purchase_statistics(self, current)
    }
}

fn validate_purchase_statistics(catalog: &HeroBuildCatalog, required: bool) -> Result<()> {
    let mut hero_counts = BTreeMap::new();
    let mut item_counts = BTreeMap::new();
    for hero in &catalog.heroes {
        for item in hero.core.iter().chain(&hero.situational) {
            let Some(statistics) = &item.statistics else {
                if required {
                    return Err(Error::new(
                        "Current builds require item purchase statistics",
                    ));
                }
                continue;
            };
            statistics.validate()?;
            if statistics.hero_matches > catalog.cohort.player_matches
                || hero_counts
                    .insert(hero.hero_id, statistics.hero_matches)
                    .is_some_and(|previous| previous != statistics.hero_matches)
                || item_counts
                    .insert((hero.hero_id, item.item_id), statistics)
                    .is_some_and(|previous| previous != statistics)
            {
                return Err(Error::new(
                    "Item purchase statistics disagree across the hero cohort",
                ));
            }
        }
    }
    Ok(())
}

fn validate_hero(hero: &HeroBuild) -> Result<()> {
    validate_variant_id(hero.variant_id.as_deref())?;
    if let Some(focus) = &hero.ability_focus {
        focus.validate(hero)?;
    }
    let context = || format!("Build for {}", hero.hero_name);
    if hero.hero_id == 0 || hero.hero_name.trim().is_empty() || hero.core.is_empty() {
        return Err(Error::new(format!(
            "{} requires a hero and CORE items",
            context()
        )));
    }
    if hero.key_item().is_none() {
        return Err(Error::new(format!(
            "{} has a key item outside CORE",
            context()
        )));
    }
    let mut items = BTreeSet::new();
    for item in hero.core.iter().chain(&hero.situational) {
        if let Some(target) = &item.imbue_target {
            target.validate()?;
            if !hero.ability_ids.contains(&target.ability_id) {
                return Err(Error::new(
                    "Item imbue target is absent from the hero ability order",
                ));
            }
        }
        if !items.insert(item.item_id)
            || !(1..=4).contains(&item.tier)
            || !(0.0..=1.0).contains(&item.adoption)
            || !(0.0..=1.0).contains(&item.win_rate)
            || !item.effect.is_finite()
        {
            return Err(Error::new(format!(
                "{} has a repeated or invalid item",
                context()
            )));
        }
    }
    let evaluation = &hero.evaluation;
    if !evaluation.agreement_coefficient.is_finite()
        || !evaluation.standard_error.is_finite()
        || evaluation.standard_error < 0.0
        || Confidence::classify(evaluation.agreement_coefficient, evaluation.standard_error)
            != evaluation.confidence
    {
        return Err(Error::new(format!(
            "{} has an inconsistent evaluation",
            context()
        )));
    }
    Ok(())
}

fn validate_variant_id(variant: Option<&str>) -> Result<()> {
    if let Some(variant) = variant
        && (variant.is_empty()
            || variant.len() > 80
            || !variant
                .bytes()
                .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'-'))
    {
        return Err(Error::new(
            "Build variant requires 1 to 80 lowercase letters, digits, or hyphens",
        ));
    }
    Ok(())
}
