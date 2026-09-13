use std::collections::BTreeMap;
use std::path::Path;

use deadlock_data::Result;
use deadlock_guides::{
    BuildEvidenceCatalog, NarrativeCatalog, PolicyArtifact, StrategyContext,
    load_artifact_guide_bundle,
};
use deadlock_input::DeadlockApi;
use deadlock_steam::{BuildKey, CacheLocation, managed_builds_match, read_cache};
use serde_json::{Value, json};

pub fn build_freshness_report(
    directory: &Path,
    api: &mut DeadlockApi,
    location: Result<CacheLocation>,
) -> Result<(u8, Value)> {
    let client = api.resolve_client_version()?;
    let patch = api.current_patch()?;
    let (mut evidence_stage, evidence) = load_artifact_status(
        &directory.join("build-evidence.json"),
        "build_evidence",
        BuildEvidenceCatalog::read,
    );
    if let Some(evidence) = &evidence
        && (evidence.metadata().client_version != client
            || evidence.metadata().patch.get("identity") != Some(&patch.identity()?.into()))
    {
        mark_stale(
            &mut evidence_stage,
            "Build evidence uses another patch or client version",
        );
    }
    let (mut context_stage, context) = load_artifact_status(
        &directory.join("strategy-context.json"),
        "strategy_context",
        StrategyContext::load,
    );
    if let Some(context) = &context
        && let Some(evidence) = &evidence
    {
        let manifest = context.manifest().content();
        let metadata = evidence.metadata();
        if manifest.client_version != metadata.client_version
            || manifest.as_of_timestamp != metadata.as_of_timestamp
            || manifest.patch.get("identity") != metadata.patch.get("identity")
        {
            mark_stale(&mut context_stage, "Snapshot differs from build evidence");
        }
    }
    let stages = vec![
        evidence_stage,
        context_stage,
        check_policy_status(directory, context.as_ref())?,
        check_narrative_status(directory, context.as_ref()),
        check_bundle_status(directory),
        check_installation_status(location, directory),
    ];
    let code = if stages.iter().all(|stage| stage["state"] == "current") {
        0
    } else if stages
        .iter()
        .any(|stage| matches!(stage["state"].as_str(), Some("malformed" | "unavailable")))
    {
        1
    } else {
        2
    };
    Ok((
        code,
        json!({"status":match code {0 => "current", 1 => "invalid_or_unavailable", _ => "regeneration_required"},
        "latest_client_version":client,"latest_patch":patch.to_document()?,"stages":stages}),
    ))
}

fn load_artifact_status<T>(
    path: &Path,
    name: &str,
    load: impl FnOnce(&Path) -> Result<T>,
) -> (Value, Option<T>) {
    if !path.is_file() {
        return (
            build_stage_status(name, "missing", &path.display().to_string()),
            None,
        );
    }
    match load(path) {
        Ok(value) => (
            build_stage_status(name, "current", "Validated"),
            Some(value),
        ),
        Err(error) => (
            build_stage_status(name, "malformed", &error.to_string()),
            None,
        ),
    }
}

fn build_stage_status(name: &str, state: &str, detail: &str) -> Value {
    json!({"stage":name,"state":state,"detail":detail})
}

fn mark_stale(stage: &mut Value, detail: &str) {
    stage["state"] = "stale".into();
    stage["detail"] = detail.into();
}

fn check_policy_status(directory: &Path, context: Option<&StrategyContext>) -> Result<Value> {
    let (mut stage, policies) = load_artifact_status(
        &directory.join("policies.json"),
        "policies",
        PolicyArtifact::load,
    );
    if let Some(policies) = policies
        && let Some(context) = context
        && policies.manifest().to_document()? != context.manifest().to_document()?
    {
        mark_stale(&mut stage, "Snapshot differs from strategy context");
    }
    Ok(stage)
}

fn check_narrative_status(directory: &Path, context: Option<&StrategyContext>) -> Value {
    let (mut stage, narratives) = load_artifact_status(
        &directory.join("narratives.json"),
        "narratives",
        NarrativeCatalog::load,
    );
    if let Some(narratives) = narratives
        && let Some(context) = context
        && narratives.snapshot_id() != context.manifest().identifier()
    {
        mark_stale(&mut stage, "Snapshot differs from strategy context");
    }
    stage
}

fn check_bundle_status(directory: &Path) -> Value {
    if [
        "strategy-context.json",
        "policies.json",
        "narratives.json",
        "build-evidence.json",
    ]
    .iter()
    .any(|name| !directory.join(name).is_file())
    {
        return build_stage_status(
            "artifact_bundle",
            "missing",
            "One or more required artifact files are missing",
        );
    }
    match load_artifact_guide_bundle(
        &directory.join("strategy-context.json"),
        &directory.join("policies.json"),
        &directory.join("narratives.json"),
        &directory.join("build-evidence.json"),
    ) {
        Ok(bundle) => build_stage_status(
            "artifact_bundle",
            "current",
            &format!("Validated {} reviewed guides", bundle.guides.len()),
        ),
        Err(error) => build_stage_status("artifact_bundle", "malformed", &error.to_string()),
    }
}

fn check_installation_status(location: Result<CacheLocation>, directory: &Path) -> Value {
    let location = match location {
        Ok(location) => location,
        Err(error) => {
            return build_stage_status("installed_cache", "unavailable", &error.to_string());
        }
    };
    match compare_installed_guides(&location, directory) {
        Ok(true) => build_stage_status("installed_cache", "current", "Validated"),
        Ok(false) => build_stage_status(
            "installed_cache",
            "stale",
            "Managed builds differ from the expected coverage or guide contents",
        ),
        Err(error) => build_stage_status("installed_cache", "malformed", &error.to_string()),
    }
}

fn compare_installed_guides(location: &CacheLocation, directory: &Path) -> Result<bool> {
    let bundle = load_artifact_guide_bundle(
        &directory.join("strategy-context.json"),
        &directory.join("policies.json"),
        &directory.join("narratives.json"),
        &directory.join("build-evidence.json"),
    )?;
    let expected = bundle
        .guides
        .iter()
        .map(|guide| {
            let presentation = deadlock_guides::build_presentation(
                guide,
                "Build Preview",
                &bundle.patch.title,
                &bundle.patch.published_at,
                bundle.rank_range,
            )?;
            Ok((
                BuildKey {
                    hero_id: guide.hero_id,
                    path_id: guide.path_id.clone(),
                },
                presentation,
            ))
        })
        .collect::<Result<BTreeMap<_, _>>>()?;
    managed_builds_match(
        &read_cache(&location.cache_path)?,
        location.account_id,
        &expected,
    )
}
