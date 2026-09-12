use std::collections::{BTreeMap, BTreeSet};

use chrono::DateTime;
use deadlock_data::{ArtifactCoverage, Error, Result, integer, text};
use serde_json::{Value, json};

use crate::context_validation::StrategyContext;
use crate::narrative_catalog::{
    NARRATIVE_GENERATOR_VERSION, NARRATIVE_SCHEMA_VERSION, NarrativeCatalog, NarrativeEntry,
};
use crate::narrative_description::build_deterministic_description;

#[derive(Debug)]
pub struct NarrativeGeneration {
    pub catalog: NarrativeCatalog,
    pub written: usize,
    pub reused: usize,
}

/// # Errors
/// Returns an error when source identities are incomplete or the description cannot meet its length limits.
pub fn generate_deterministic_narrative(hero: &Value) -> Result<NarrativeEntry> {
    let id = integer(hero, "hero_id")?;
    let entry = NarrativeEntry {
        hero_id: id,
        path_id: text(hero, "path_id")?.into(),
        hero: hero["hero"]
            .as_str()
            .filter(|name| !name.is_empty())
            .map_or_else(|| id.to_string(), str::to_owned),
        snapshot_id: text(hero, "snapshot_id")?.into(),
        policy_id: text(hero, "policy_id")?.into(),
        context_sha256: text(hero, "context_sha256")?.into(),
        narrative_basis_sha256: text(hero, "narrative_basis_sha256")?.into(),
        generator_version: NARRATIVE_GENERATOR_VERSION,
        build_description: build_deterministic_description(hero)?,
    };
    entry.validate()?;
    Ok(entry)
}

/// # Errors
/// Returns an error when selectors, source identities, descriptions, or the completed artifact fail validation.
pub fn generate_narrative_document(
    source: &StrategyContext,
    selectors: &[String],
    existing: Option<&NarrativeCatalog>,
    force: bool,
    generated_at: &str,
) -> Result<NarrativeGeneration> {
    DateTime::parse_from_rfc3339(generated_at)
        .map_err(|error| Error::new(format!("Invalid generation timestamp: {error}")))?;
    let selected = select_heroes(source, selectors)?;
    let mut requested = BTreeSet::new();
    let mut entries = Vec::new();
    let mut reused = 0;
    for hero in selected {
        let entry = generate_deterministic_narrative(hero)?;
        requested.insert(entry.hero_id);
        let key = (entry.hero_id, entry.path_id.clone());
        if !force && existing.is_some_and(|catalog| catalog.heroes().get(&key) == Some(&entry)) {
            reused += 1;
        }
        entries.push(entry);
    }
    let exclusions = if selectors.is_empty() {
        source.coverage().exclusions().clone()
    } else {
        BTreeMap::new()
    };
    requested.extend(exclusions.keys());
    let coverage = ArtifactCoverage::new(requested, exclusions)?;
    let manifest = source.manifest().content();
    let mut document = Value::Object(coverage.document_fields());
    document["schema_version"] = NARRATIVE_SCHEMA_VERSION.into();
    document["generator_version"] = NARRATIVE_GENERATOR_VERSION.into();
    document["generator"] = "deadlock-build-sync deterministic description".into();
    document["generated_at"] = generated_at.into();
    document["source_context_sha256"] = source.document()["source_context_sha256"].clone();
    document["snapshot_id"] = source.manifest().identifier().into();
    document["patch"] = source.document()["patch"].clone();
    document["cohort"] = json!({"client_version":manifest.client_version,"match_mode":manifest.match_mode,"game_mode":manifest.game_mode,
        "rank_range":manifest.rank_range,"as_of_timestamp":manifest.as_of_timestamp});
    document["heroes"] = serde_json::to_value(&entries)?;
    Ok(NarrativeGeneration {
        catalog: NarrativeCatalog::from_document(document)?,
        written: entries.len() - reused,
        reused,
    })
}

fn select_heroes<'source>(
    source: &'source StrategyContext,
    selectors: &[String],
) -> Result<Vec<&'source Value>> {
    if selectors.is_empty() {
        return Ok(source.heroes().values().collect());
    }
    let requested = selectors
        .iter()
        .map(|selector| normalize_selector(selector))
        .collect::<BTreeSet<_>>();
    let mut matched = BTreeSet::new();
    let mut selected = Vec::new();
    for ((id, _), hero) in source.heroes() {
        let names = [
            id.to_string(),
            normalize_selector(hero["hero"].as_str().unwrap_or_default()),
        ];
        if names.iter().any(|name| requested.contains(name)) {
            matched.extend(names);
            selected.push(hero);
        }
    }
    let missing = requested.difference(&matched).cloned().collect::<Vec<_>>();
    if !missing.is_empty() {
        return Err(Error::new(format!(
            "Hero selectors were not found: {}",
            missing.join(", ")
        )));
    }
    Ok(selected)
}

fn normalize_selector(value: &str) -> String {
    value.to_lowercase().replace(' ', "")
}
