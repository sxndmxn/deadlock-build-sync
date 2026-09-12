use deadlock_data::{Error, Result, fingerprint, sha256};
use deadlock_guides::{
    BuildEvidenceCatalog, DecisionState, PolicyArtifact, recommend, render_recommendation_markdown,
};
use deadlock_input::{ApiOptions, DeadlockApi};

use crate::cli_arguments::{OutputFormat, RecommendArguments};
use crate::cli_generation::require_current_evidence;
use crate::cli_output::{print_json, print_text};
use crate::cli_paths::{absolute_path, evidence_path};

pub fn run_recommend(args: &RecommendArguments, base_url: &str) -> Result<u8> {
    let evidence_path = evidence_path(args.build_evidence.as_deref(), args.artifacts.as_deref())?;
    let evidence = require_current_evidence(&evidence_path, base_url)?;
    let state = DecisionState::load(&absolute_path(&args.state)?)?;
    let policy_path = args
        .policies
        .as_deref()
        .map(absolute_path)
        .transpose()?
        .unwrap_or_else(|| evidence_path.with_file_name("policies.json"));
    let policies = PolicyArtifact::load(&policy_path)?;
    validate_policy_evidence(&policies, &evidence)?;
    let hero_id = state.content().hero_id;
    let path_id = state
        .content()
        .path_id
        .as_deref()
        .or_else(|| {
            evidence
                .heroes()
                .get(&hero_id)?
                .builds
                .first()
                .map(|build| build.path_id.as_str())
        })
        .unwrap_or("default");
    let policy = policies
        .policies()
        .get(&(hero_id, path_id.into()))
        .ok_or_else(|| Error::new("Decision state hero and path are absent from typed policies"))?;
    let metadata = evidence.metadata();
    let mut api = DeadlockApi::new(ApiOptions {
        base_url: base_url.into(),
        client_version: Some(metadata.client_version),
        as_of_timestamp: metadata.as_of_timestamp,
        epochs: Some(metadata.epochs.clone()),
        ..ApiOptions::default()
    })?;
    let assets = api.items()?;
    if fingerprint(&serde_json::to_value(&assets)?)? != metadata.items_sha256 {
        return Err(Error::new(
            "Current item assets differ from the evidence assets",
        ));
    }
    let recommendation = recommend(&evidence, policy, &state, &assets)?;
    if args.format == OutputFormat::Markdown {
        print_text(&render_recommendation_markdown(&recommendation)?)?;
    } else {
        print_json(&serde_json::to_value(recommendation)?)?;
    }
    Ok(0)
}

fn validate_policy_evidence(
    policies: &PolicyArtifact,
    evidence: &BuildEvidenceCatalog,
) -> Result<()> {
    let manifest = policies.manifest().content();
    let metadata = evidence.metadata();
    let same = manifest.client_version == metadata.client_version
        && manifest.as_of_timestamp == metadata.as_of_timestamp
        && manifest.epochs == metadata.epochs
        && manifest.patch.get("identity") == metadata.patch.get("identity")
        && metadata
            .cohort
            .get("match_mode")
            .and_then(serde_json::Value::as_str)
            .is_some_and(|mode| mode.eq_ignore_ascii_case(manifest.match_mode.as_str()))
        && metadata
            .cohort
            .get("game_mode")
            .and_then(serde_json::Value::as_str)
            .is_some_and(|mode| mode.eq_ignore_ascii_case(&manifest.game_mode));
    let records = manifest
        .records
        .iter()
        .filter(|record| record.path == "artifact:build-evidence")
        .collect::<Vec<_>>();
    if !same
        || records.len() != 1
        || records
            .first()
            .is_none_or(|record| record.sha256 != sha256(evidence.raw_bytes()))
    {
        return Err(Error::new(
            "Typed policy sidecar differs from the current build evidence",
        ));
    }
    Ok(())
}
