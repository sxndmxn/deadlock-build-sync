use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{ArtifactCoverage, Error, RankCatalog, RankRange, Result, SnapshotManifest};
use deadlock_guides::{
    AbilityTimelineStep, BuildEvidenceCatalog, BuildPolicy, DurationDistribution, GuideGroupIndex,
    PurchaseGuide, SelectedHeroBuild, SituationalPolicy,
};
use deadlock_input::{HeroDurationStat, Patch};
use serde_json::{Map, Value};

#[derive(Clone, Debug)]
pub struct GeneratedGuides {
    pub evidence: BuildEvidenceCatalog,
    pub guides: Vec<PurchaseGuide>,
    pub policies: Vec<BuildPolicy>,
    pub contexts: Vec<Value>,
    pub item_mechanics: Map<String, Value>,
    pub coverage: ArtifactCoverage,
    pub eligible_hero_ids: BTreeSet<u64>,
    pub subset_selected: bool,
    pub rank_range: RankRange,
    pub rank_catalog: RankCatalog,
    pub persona: String,
    pub patch: Patch,
    pub manifest: SnapshotManifest,
    pub guide_groups: GuideGroupIndex,
}

impl GeneratedGuides {
    /// # Errors
    /// Returns an error when no guides exist or the requested roster has incomplete coverage.
    pub fn require_complete(&self) -> Result<()> {
        if self.guides.is_empty() || !self.coverage.exclusions().is_empty() {
            return Err(Error::new(
                "Requested heroes have no complete supported builds",
            ));
        }
        self.coverage.validate_keys(
            self.guides
                .iter()
                .map(|guide| (guide.hero_id, guide.path_id.as_str())),
        )
    }
}

#[derive(Clone, Debug)]
pub struct HeroInputs {
    pub selected: SelectedHeroBuild,
    pub guide: PurchaseGuide,
    pub kit: Value,
    pub timeline: Vec<AbilityTimelineStep>,
    pub duration: Vec<HeroDurationStat>,
    pub distribution: DurationDistribution,
    pub matchups: Value,
    pub situational: SituationalPolicy,
}

#[derive(Debug)]
pub struct CohortAnalytics {
    pub duration: BTreeMap<u64, Vec<HeroDurationStat>>,
    pub distribution: DurationDistribution,
    pub same_lane: BTreeMap<u64, Vec<Value>>,
    pub whole_team: BTreeMap<u64, Vec<Value>>,
}

/// # Errors
/// Returns an error when the query is absent, unknown, or ambiguous.
pub fn select_heroes(heroes: &[Value], query: Option<&str>, all: bool) -> Result<Vec<Value>> {
    if all {
        return Ok(heroes.to_vec());
    }
    let query = query.ok_or_else(|| Error::new("Supply --hero NAME or --all"))?;
    let normalized = normalize_hero(query);
    let selected = heroes
        .iter()
        .filter(|hero| {
            let id = hero["id"]
                .as_u64()
                .map_or_else(String::new, |id| id.to_string());
            let name = normalize_hero(hero["name"].as_str().unwrap_or_default());
            let class = hero["class_name"]
                .as_str()
                .unwrap_or_default()
                .to_lowercase();
            [
                id.as_str(),
                name.as_str(),
                class.strip_prefix("hero_").unwrap_or(&class),
            ]
            .contains(&normalized.as_str())
        })
        .cloned()
        .collect::<Vec<_>>();
    match selected.len() {
        0 => Err(Error::new(format!("Active hero was not found: {query}"))),
        1 => Ok(selected),
        _ => Err(Error::new(format!(
            "Hero query has more than one match: {query}"
        ))),
    }
}

fn normalize_hero(value: &str) -> String {
    value.to_lowercase().replace(' ', "").replace('&', "and")
}
