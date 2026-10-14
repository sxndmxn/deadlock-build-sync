use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;

use deadlock_data::{Error, Result, atomic_write_json, count_as_f64, read_json};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

pub const HERO_BUILD_SCHEMA_VERSION: u32 = 8;
pub const HERO_BUILD_METHOD: &str = "item-effect-counters-v1";
/// The largest number of items in one counter panel.
pub const MAXIMUM_COUNTER_ITEMS: usize = 4;
/// A counter phase with a z value below this limit contradicts the counter effect.
pub const COUNTER_CONTRADICTION_Z: f64 = -2.0;

/// All hero builds from one source snapshot.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HeroBuildCatalog {
    pub schema_version: u32,
    pub method: String,
    pub client_version: u64,
    pub patch: Map<String, Value>,
    pub cohort: BuildCohort,
    /// Run evidence for each counter item group that passed its test.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub counter_evidence: Vec<CounterEvidence>,
    pub heroes: Vec<HeroBuild>,
}

/// The enemy team property that a counter panel answers.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CounterTarget {
    /// The enemy team deals mostly weapon damage.
    Weapon,
    /// The enemy team deals mostly spirit damage.
    Spirit,
    /// The enemy team owns many healing and lifesteal items.
    Sustain,
}

impl CounterTarget {
    #[must_use]
    pub const fn panel_name(self) -> &'static str {
        match self {
            Self::Weapon => "VS WEAPON",
            Self::Spirit => "VS SPIRIT",
            Self::Sustain => "VS SUSTAIN",
        }
    }

    #[must_use]
    pub const fn label(self) -> &'static str {
        match self {
            Self::Weapon => "weapon",
            Self::Spirit => "spirit",
            Self::Sustain => "sustain",
        }
    }

    /// Describes the match condition in which the panel applies.
    #[must_use]
    pub const fn condition(self) -> &'static str {
        match self {
            Self::Weapon => "most enemy damage is weapon damage",
            Self::Spirit => "most enemy damage is spirit damage",
            Self::Sustain => "the enemy team buys healing and lifesteal items",
        }
    }
}

/// Run evidence that the items of one group win more against one enemy team property.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CounterEvidence {
    pub target: CounterTarget,
    pub phases: Vec<CounterPhase>,
}

/// The counter test of one item group at one phase landmark.
///
/// The coefficient is the change in log-odds for each owned group item when the enemy
/// condition of this target is one standard deviation above its mean.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CounterPhase {
    pub phase_s: u32,
    pub coefficient: f64,
    pub standard_error: f64,
    pub observations: u64,
}

/// Counter items that this hero buys against one enemy team property.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CounterPanel {
    pub target: CounterTarget,
    pub items: Vec<BuildItem>,
}

impl CounterPhase {
    /// Returns the coefficient divided by its standard error.
    #[must_use]
    pub fn z(&self) -> f64 {
        self.coefficient / self.standard_error
    }
}

impl CounterEvidence {
    /// Returns true unless a phase contradicts the counter effect with a z value below −2.
    ///
    /// Four patches confirmed the effect. Thus, a short run with weak evidence keeps the panel,
    /// and only clear contrary evidence removes it. See E7 in `docs/research-log.md`.
    #[must_use]
    pub fn is_supported(&self) -> bool {
        self.phases
            .iter()
            .all(|phase| phase.z() >= COUNTER_CONTRADICTION_Z)
    }

    /// # Errors
    /// Returns an error for invalid values or a phase that contradicts the counter effect.
    pub fn validate(&self) -> Result<()> {
        if self.phases.is_empty()
            || self.phases.iter().any(|phase| {
                !phase.coefficient.is_finite()
                    || !phase.standard_error.is_finite()
                    || phase.standard_error <= 0.0
                    || phase.observations == 0
            })
            || !self.is_supported()
        {
            return Err(Error::new(
                "Counter evidence requires valid phases without a contradiction",
            ));
        }
        Ok(())
    }
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
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub counters: Vec<CounterPanel>,
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
    /// The test of this build alone, before the pull toward comparable builds of all heroes.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub hero_estimate: Option<HeroEstimate>,
}

/// The agreement coefficient of one build's own held-out test.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HeroEstimate {
    pub agreement_coefficient: f64,
    pub standard_error: f64,
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

    /// Returns the CORE, situational, and counter items of the build.
    pub fn items(&self) -> impl Iterator<Item = &BuildItem> {
        self.core
            .iter()
            .chain(&self.situational)
            .chain(self.counters.iter().flat_map(|panel| &panel.items))
    }

    /// Returns the CORE, situational, and counter items of the build for changes.
    pub fn items_mut(&mut self) -> impl Iterator<Item = &mut BuildItem> {
        self.core
            .iter_mut()
            .chain(&mut self.situational)
            .chain(self.counters.iter_mut().flat_map(|panel| &mut panel.items))
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
            (6, "item-effect-variants-v1") | (7, "item-effect-variants-v2") => true,
            _ => false,
        };
        let mut targets = BTreeSet::new();
        for evidence in &self.counter_evidence {
            evidence.validate()?;
            if !targets.insert(evidence.target) {
                return Err(Error::new("Counter evidence repeats a damage type"));
            }
        }
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
            validate_counters(hero, &targets)?;
        }
        validate_purchase_statistics(self, current)
    }
}

fn validate_purchase_statistics(catalog: &HeroBuildCatalog, required: bool) -> Result<()> {
    let mut hero_counts = BTreeMap::new();
    let mut item_counts = BTreeMap::new();
    for hero in &catalog.heroes {
        for item in hero.items() {
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

/// Checks that each counter panel has tested evidence and distinct valid items outside CORE.
fn validate_counters(hero: &HeroBuild, targets: &BTreeSet<CounterTarget>) -> Result<()> {
    let mut panels = BTreeSet::new();
    for panel in &hero.counters {
        let mut items = BTreeSet::new();
        if !targets.contains(&panel.target)
            || !panels.insert(panel.target)
            || !(1..=MAXIMUM_COUNTER_ITEMS).contains(&panel.items.len())
            || panel.items.iter().any(|item| {
                !items.insert(item.item_id)
                    || hero.core.iter().any(|core| core.item_id == item.item_id)
                    || !(1..=4).contains(&item.tier)
                    || !(0.0..=1.0).contains(&item.adoption)
                    || !(0.0..=1.0).contains(&item.win_rate)
                    || !item.effect.is_finite()
            })
        {
            return Err(Error::new(format!(
                "Build for {} has an invalid counter panel",
                hero.hero_name
            )));
        }
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
