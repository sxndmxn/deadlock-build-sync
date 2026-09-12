use std::collections::BTreeMap;

use deadlock_data::{Error, Result};

use crate::evidence_catalog_header::{BuildEvidenceMetadata, BuildGenerator};
use crate::evidence_values::integer;
use crate::generator_evidence::validate_generator_group;
use crate::hero_evidence::{HeroBuildEvidence, HeroEvidence};

pub fn validate_hero_groups(hero: &HeroEvidence, metadata: &BuildEvidenceMetadata) -> Result<()> {
    let mut groups = BTreeMap::<&str, Vec<&HeroBuildEvidence>>::new();
    for build in &hero.builds {
        let cohort = build.cohort.content();
        if metadata
            .cohort
            .get("maximum_badge")
            .and_then(serde_json::Value::as_u64)
            != Some(u64::from(cohort.maximum_badge.badge()))
            || cohort
                .expansion_history
                .first()
                .and_then(|row| row.get("minimum_badge"))
                != metadata.cohort.get("minimum_badge")
        {
            return Err(Error::new("Hero ranks differ from the starting cohort"));
        }
        groups.entry(&build.guide_group_id).or_default().push(build);
    }
    for (group_id, members) in groups {
        let default = primary_build(members.iter().copied())?
            .ok_or_else(|| Error::new("Guide group has no default build"))?;
        if group_id != default.path_id {
            return Err(Error::new("Guide group differs from its frozen default"));
        }
        match metadata.generator {
            BuildGenerator::Current => validate_current_group(&members)?,
            BuildGenerator::Beam => validate_beam_group(&members, default)?,
        }
    }
    Ok(())
}

pub fn primary_build<'build>(
    builds: impl Iterator<Item = &'build HeroBuildEvidence>,
) -> Result<Option<&'build HeroBuildEvidence>> {
    let mut best = None;
    let mut best_rank = u64::MAX;
    for build in builds {
        let rank = integer(
            &build.discovery["selection_rank"],
            "frozen selection rank",
            0,
        )?;
        if best.is_none() || rank < best_rank {
            best = Some(build);
            best_rank = rank;
        }
    }
    Ok(best)
}

fn validate_current_group(members: &[&HeroBuildEvidence]) -> Result<()> {
    if members.iter().any(|build| build.generator.is_some()) {
        return Err(Error::new("Current evidence cannot contain beam paths"));
    }
    if members
        .iter()
        .any(|build| build.discovery["method"].as_str() != Some("eclat_leiden_pairwise"))
    {
        return Err(Error::new("Current evidence cannot contain beam discovery"));
    }
    Ok(())
}

fn validate_beam_group(members: &[&HeroBuildEvidence], default: &HeroBuildEvidence) -> Result<()> {
    let records = members
        .iter()
        .map(|build| {
            let record = build
                .generator
                .as_ref()
                .ok_or_else(|| Error::new("Beam group lacks generator records"))?;
            Ok((record, &build.discovery))
        })
        .collect::<Result<Vec<_>>>()?;
    let default = default
        .generator
        .as_ref()
        .ok_or_else(|| Error::new("Beam default lacks generator evidence"))?;
    validate_generator_group(&records, default)
}
