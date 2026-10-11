use std::collections::BTreeSet;
use std::path::Path;

use deadlock_data::{Error, Result, atomic_write_json, read_json};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

pub const HERO_BUILD_SCHEMA_VERSION: u32 = 3;
pub const HERO_BUILD_METHOD: &str = "item-effect-ridge-v1";

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
    pub title: String,
    pub tag_ids: [u64; 3],
    pub key_ability_name: Option<String>,
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
    pub adoption: f64,
    pub win_rate: f64,
    pub effect: f64,
    pub median_net_worth: u32,
    /// The lower and upper quartile of net worth at the first purchase.
    pub soul_window: [u32; 2],
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
    /// Returns the managed Steam build identity for this hero.
    #[must_use]
    pub fn path_id(&self) -> String {
        format!("{}-main", self.hero_id)
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
    /// Returns an error for an unsupported schema or method, repeated heroes, or an invalid build.
    pub fn validate(&self) -> Result<()> {
        if self.schema_version != HERO_BUILD_SCHEMA_VERSION || self.method != HERO_BUILD_METHOD {
            return Err(Error::new(
                "Hero builds use another schema or method. Run deadlock-build-sync sync",
            ));
        }
        if self.cohort.minimum_badge > self.cohort.maximum_badge {
            return Err(Error::new("Hero build cohort has an invalid rank range"));
        }
        let mut heroes = BTreeSet::new();
        for hero in &self.heroes {
            if !heroes.insert(hero.hero_id) {
                return Err(Error::new("Hero builds repeat a hero"));
            }
            validate_hero(hero)?;
        }
        Ok(())
    }
}

fn validate_hero(hero: &HeroBuild) -> Result<()> {
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
