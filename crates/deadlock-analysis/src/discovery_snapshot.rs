use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{
    Error, Result, atomic_write_json, canonical_json, file_sha256, fingerprint, integer, read_json,
    sha256,
};
use deadlock_guides::CURRENT_METHOD_VERSION;
use serde_json::{Value, json};

use crate::config::RunPaths;
use crate::core_discovery::assign_group_ids;
use crate::discovery_models::FrozenHero;

pub type FrozenRoster = BTreeMap<u64, FrozenHero>;
pub type GuideGroups = BTreeMap<u64, BTreeMap<String, String>>;

pub fn source_identity(paths: &RunPaths) -> Result<Value> {
    let mut hashes = BTreeMap::new();
    for name in [
        "manifest.json",
        "raw/analysis.duckdb",
        "raw/heroes.json",
        "raw/items.json",
        "raw/items-all.json",
        "raw/ranks.json",
        "raw/patches.json",
    ] {
        hashes.insert(name, file_sha256(&paths.run.join(name))?);
    }
    Ok(json!({"schema_version":1,"method_version":CURRENT_METHOD_VERSION,"files":hashes}))
}

pub fn require_source_identity(paths: &RunPaths, expected: &Value) -> Result<()> {
    if source_identity(paths)? != *expected {
        return Err(Error::new(
            "Discovery source identity differs. Start a new --run-id.",
        ));
    }
    Ok(())
}

pub fn roster_fingerprint(frozen: &FrozenRoster) -> Result<String> {
    let mut bytes = vec![b'{'];
    for (index, (hero, record)) in frozen.iter().enumerate() {
        if index > 0 {
            bytes.push(b',');
        }
        bytes.extend(serde_json::to_vec(&hero.to_string())?);
        bytes.push(b':');
        bytes.extend(canonical_json(&serde_json::to_value(record)?)?);
    }
    bytes.push(b'}');
    Ok(sha256(&bytes))
}

pub fn save_snapshot(
    paths: &RunPaths,
    frozen: &FrozenRoster,
    groups: &GuideGroups,
    source: &Value,
) -> Result<String> {
    require_source_identity(paths, source)?;
    let digest = roster_fingerprint(frozen)?;
    atomic_write_json(
        &paths
            .run
            .join(format!("discovery-nominations-{}.json", &digest[..16])),
        &serde_json::to_value(frozen)?,
    )?;
    atomic_write_json(
        &paths
            .run
            .join(format!("guide-groups-{}.json", &digest[..16])),
        &json!({"frozen_sha256":digest,"groups":groups,"source_identity":source}),
    )?;
    Ok(digest)
}

pub fn load_snapshot(paths: &RunPaths, heroes: &[Value]) -> Result<(FrozenRoster, GuideGroups)> {
    let mut candidates = Vec::new();
    for entry in std::fs::read_dir(&paths.run)? {
        let entry = entry?;
        let name = entry.file_name();
        let name = name.to_string_lossy();
        if name.starts_with("discovery-nominations-") && name.ends_with(".json") {
            candidates.push(entry.path());
        }
    }
    if candidates.len() != 1 {
        return Err(Error::new(
            "Resume requires one complete discovery snapshot",
        ));
    }
    let document = read_json(&candidates[0])?;
    let frozen: FrozenRoster = serde_json::from_value(document)?;
    let expected = heroes
        .iter()
        .map(|hero| integer(hero, "id"))
        .collect::<Result<BTreeSet<_>>>()?;
    if frozen.keys().copied().collect::<BTreeSet<_>>() != expected {
        return Err(Error::new(
            "Discovery snapshot does not cover the requested heroes",
        ));
    }
    let digest = roster_fingerprint(&frozen)?;
    if candidates[0].file_name().and_then(|name| name.to_str())
        != Some(&format!("discovery-nominations-{}.json", &digest[..16]))
    {
        return Err(Error::new("Discovery snapshot fingerprint does not match"));
    }
    let group_document = read_json(
        &paths
            .run
            .join(format!("guide-groups-{}.json", &digest[..16])),
    )?;
    require_source_identity(paths, &group_document["source_identity"])?;
    let groups = frozen
        .iter()
        .map(|(hero, report)| Ok((*hero, assign_group_ids(&report.rows)?)))
        .collect::<Result<GuideGroups>>()?;
    let expected = json!({"frozen_sha256":digest,"groups":groups,"source_identity":group_document["source_identity"]});
    if fingerprint(&group_document)? != fingerprint(&expected)? {
        return Err(Error::new("Discovery snapshot guide groups do not match"));
    }
    Ok((frozen, groups))
}
