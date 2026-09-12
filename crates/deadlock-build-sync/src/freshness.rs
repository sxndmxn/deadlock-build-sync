use std::collections::BTreeMap;
use std::path::Path;

use deadlock_data::Result;
use deadlock_guides::{
    BuildEvidenceCatalog, NarrativeCatalog, PolicyArtifact, StrategyContext,
    load_artifact_guide_bundle,
};
use deadlock_input::DeadlockApi;
use deadlock_steam::{BuildKey, CacheLocation, managed_build_descriptions, read_cache};
use serde_json::{Value, json};

pub fn build_freshness_report(
    directory: &Path,
    api: &mut DeadlockApi,
    location: Result<CacheLocation>,
) -> Result<(u8, Value)> {
    let client = api.resolve_client_version()?;
    let patch = api.current_patch()?;
    let (mut evidence_stage, evidence) = check_file(
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
    let (mut context_stage, context) = check_file(
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
        policy_stage(directory, context.as_ref())?,
        narrative_stage(directory, context.as_ref()),
        bundle_stage(directory),
        installed_stage(location, directory),
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

fn check_file<T>(
    path: &Path,
    name: &str,
    load: impl FnOnce(&Path) -> Result<T>,
) -> (Value, Option<T>) {
    if !path.is_file() {
        return (stage(name, "missing", &path.display().to_string()), None);
    }
    match load(path) {
        Ok(value) => (stage(name, "current", "Validated"), Some(value)),
        Err(error) => (stage(name, "malformed", &error.to_string()), None),
    }
}

fn stage(name: &str, state: &str, detail: &str) -> Value {
    json!({"stage":name,"state":state,"detail":detail})
}

fn mark_stale(stage: &mut Value, detail: &str) {
    stage["state"] = "stale".into();
    stage["detail"] = detail.into();
}

fn policy_stage(directory: &Path, context: Option<&StrategyContext>) -> Result<Value> {
    let (mut stage, policies) = check_file(
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

fn narrative_stage(directory: &Path, context: Option<&StrategyContext>) -> Value {
    let (mut stage, narratives) = check_file(
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

fn bundle_stage(directory: &Path) -> Value {
    if [
        "strategy-context.json",
        "policies.json",
        "narratives.json",
        "build-evidence.json",
    ]
    .iter()
    .any(|name| !directory.join(name).is_file())
    {
        return stage(
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
        Ok(bundle) => stage(
            "artifact_bundle",
            "current",
            &format!("Validated {} reviewed guides", bundle.guides.len()),
        ),
        Err(error) => stage("artifact_bundle", "malformed", &error.to_string()),
    }
}

fn installed_stage(location: Result<CacheLocation>, directory: &Path) -> Value {
    let location = match location {
        Ok(location) => location,
        Err(error) => return stage("installed_cache", "unavailable", &error.to_string()),
    };
    match compare_installed(&location, directory) {
        Ok(true) => stage("installed_cache", "current", "Validated"),
        Ok(false) => stage(
            "installed_cache",
            "stale",
            "Managed builds differ from the expected coverage, snapshot, or policy",
        ),
        Err(error) => stage("installed_cache", "malformed", &error.to_string()),
    }
}

fn compare_installed(location: &CacheLocation, directory: &Path) -> Result<bool> {
    let bundle = load_artifact_guide_bundle(
        &directory.join("strategy-context.json"),
        &directory.join("policies.json"),
        &directory.join("narratives.json"),
        &directory.join("build-evidence.json"),
    )?;
    let installed =
        managed_build_descriptions(&read_cache(&location.cache_path)?, location.account_id)?;
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
                presentation.content().description.clone(),
            ))
        })
        .collect::<Result<BTreeMap<_, _>>>()?;
    Ok(installed == expected)
}
