use deadlock_data::{Error, RankRange, Result, SnapshotManifest, sha256};
use serde_json::Value;

use crate::context_validation::StrategyContext;
use crate::evidence_catalog::BuildEvidenceCatalog;

pub fn validate_bundle_evidence(
    catalog: &BuildEvidenceCatalog,
    context: &StrategyContext,
) -> Result<()> {
    let manifest = context.manifest();
    validate_evidence_record(catalog, manifest)?;
    let snapshot = manifest.content();
    let metadata = catalog.metadata();
    let ranks = RankRange::from_document(&snapshot.rank_range.clone().into())?;
    let cohort = &metadata.cohort;
    let checks = [
        (
            "client version",
            metadata.client_version == snapshot.client_version,
        ),
        (
            "patch",
            metadata.patch.get("identity") == snapshot.patch.get("identity"),
        ),
        (
            "as-of cutoff",
            metadata.as_of_timestamp == snapshot.as_of_timestamp,
        ),
        (
            "match mode",
            cohort
                .get("match_mode")
                .and_then(Value::as_str)
                .is_some_and(|mode| mode.eq_ignore_ascii_case(snapshot.match_mode.as_str())),
        ),
        (
            "game mode",
            cohort
                .get("game_mode")
                .and_then(Value::as_str)
                .is_some_and(|mode| mode.eq_ignore_ascii_case(&snapshot.game_mode)),
        ),
        (
            "minimum rank",
            cohort.get("minimum_badge").and_then(Value::as_u64)
                == Some(u64::from(ranks.minimum.badge())),
        ),
        (
            "maximum rank",
            cohort.get("maximum_badge").and_then(Value::as_u64)
                == Some(u64::from(ranks.maximum.badge())),
        ),
        (
            "rank labels",
            metadata.rank_labels_sha256 == snapshot.rank_labels_sha256,
        ),
        ("epochs", metadata.epochs == snapshot.epochs),
        (
            "hero coverage",
            metadata.requested_hero_ids == *context.coverage().requested(),
        ),
    ];
    let differences = checks
        .into_iter()
        .filter(|(_, valid)| !valid)
        .map(|(name, _)| name)
        .collect::<Vec<_>>();
    if !differences.is_empty() {
        return Err(Error::new(format!(
            "Build evidence differs from the reviewed bundle: {}",
            differences.join(", ")
        )));
    }
    let exclusions = catalog
        .heroes()
        .values()
        .filter_map(|hero| {
            hero.exclusion
                .as_ref()
                .map(|reason| (hero.hero_id, reason.clone()))
        })
        .collect();
    if context.coverage().exclusions() != &exclusions {
        return Err(Error::new("Artifact exclusions differ from build evidence"));
    }
    Ok(())
}

fn validate_evidence_record(
    catalog: &BuildEvidenceCatalog,
    manifest: &SnapshotManifest,
) -> Result<()> {
    let records = manifest
        .content()
        .records
        .iter()
        .filter(|record| record.path == "artifact:build-evidence")
        .collect::<Vec<_>>();
    let [record] = records.as_slice() else {
        return Err(Error::new(
            "Artifact snapshot must contain one build evidence record",
        ));
    };
    if record.parameters.get("artifact_id").and_then(Value::as_str)
        != Some(catalog.metadata().artifact_id.as_str())
        || record.sha256 != sha256(catalog.raw_bytes())
        || record.byte_count != catalog.raw_bytes().len()
    {
        return Err(Error::new(
            "Build evidence bytes differ from the artifact snapshot",
        ));
    }
    Ok(())
}
