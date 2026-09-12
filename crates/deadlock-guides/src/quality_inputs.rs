use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;

use deadlock_data::{Error, Result, fingerprint, read_json};
use serde_json::Value;

use crate::ability_path::AbilityPath;
use crate::ability_reconstruction::reconstruct_ability_path;
use crate::bundle_evidence::validate_bundle_evidence;
use crate::context_validation::StrategyContext;
use crate::evidence_catalog::BuildEvidenceCatalog;
use crate::policy_artifact::PolicyArtifact;

#[derive(Debug)]
pub struct QualityInputs {
    pub evidence: BuildEvidenceCatalog,
    pub policies: PolicyArtifact,
    pub abilities: BTreeMap<String, AbilityPath>,
    pub context_sha256: String,
    pub cutoff: i64,
}

impl QualityInputs {
    /// # Errors
    /// Returns an error when artifacts have incompatible identities, incomplete coverage, or invalid ability evidence.
    pub fn load(directory: &Path) -> Result<Self> {
        let context = StrategyContext::load(&directory.join("strategy-context.json"))?;
        let policies = PolicyArtifact::load(&directory.join("policies.json"))?;
        let evidence = BuildEvidenceCatalog::read(&directory.join("build-evidence.json"))?;
        validate_bundle_evidence(&evidence, &context)?;
        if context.manifest().to_document()? != policies.manifest().to_document()? {
            return Err(Error::new("Quality artifacts use different snapshots"));
        }
        let evidence_keys = evidence
            .heroes()
            .values()
            .flat_map(|hero| &hero.builds)
            .map(|build| (build.hero_id, build.path_id.clone()))
            .collect::<BTreeSet<_>>();
        if evidence_keys != context.heroes().keys().cloned().collect()
            || evidence_keys != policies.policies().keys().cloned().collect()
        {
            return Err(Error::new("Quality artifacts cover different build paths"));
        }
        let mut abilities = BTreeMap::new();
        for (key, policy) in policies.policies() {
            let hero = &context.heroes()[key];
            if hero["policy_id"] != policy.policy_id() {
                return Err(Error::new("Quality context references another policy"));
            }
            let path = reconstruct_ability_path(hero, policy)?;
            let build = evidence.heroes()[&key.0]
                .builds
                .iter()
                .find(|build| build.path_id == key.1)
                .ok_or_else(|| Error::new("Quality build evidence is missing"))?;
            if !path.filter_item_ids.is_empty()
                && path.filter_item_ids != build.core_policy.content().backbone_item_ids
            {
                return Err(Error::new("Ability filter differs from the build backbone"));
            }
            abilities.insert(policy.policy_id().into(), path);
        }
        let created =
            chrono::DateTime::parse_from_rfc3339(&policies.manifest().content().created_at)
                .map_err(|error| Error::new(format!("Invalid frozen policy timestamp: {error}")))?
                .timestamp();
        let cutoff = created.max(evidence.metadata().as_of_timestamp);
        Ok(Self {
            evidence,
            policies,
            abilities,
            context_sha256: fingerprint(context.document())?,
            cutoff,
        })
    }

    /// # Errors
    /// Returns an error when item assets are malformed or differ from the pinned evidence assets.
    pub fn load_replay_assets(&self, path: &Path) -> Result<Vec<Value>> {
        let assets: Vec<Value> = serde_json::from_value(read_json(path)?)?;
        if assets.iter().any(|asset| !asset.is_object()) {
            return Err(Error::new("Replay assets must contain only item objects"));
        }
        let normal = assets
            .into_iter()
            .filter(|asset| {
                asset["game_mode"]
                    .as_str()
                    .unwrap_or("normal")
                    .eq_ignore_ascii_case("normal")
            })
            .collect::<Vec<_>>();
        if fingerprint(&serde_json::to_value(&normal)?)? != self.evidence.metadata().items_sha256 {
            return Err(Error::new(
                "Replay assets differ from the pinned evidence assets",
            ));
        }
        Ok(normal)
    }
}
