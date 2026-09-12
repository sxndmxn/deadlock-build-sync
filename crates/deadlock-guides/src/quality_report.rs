use deadlock_data::{Error, Result, fingerprint};
use serde_json::{Value, json};

use crate::quality_evaluation::evaluate_policy;
use crate::quality_inputs::QualityInputs;
use crate::quality_replay::ReplayCase;

/// # Errors
/// Returns an error when policy evidence is missing, replay fails, or report serialization fails.
pub fn build_quality_report(
    inputs: &QualityInputs,
    cases: &[ReplayCase],
    assets: &[Value],
    replay_sha256: Option<&str>,
) -> Result<Value> {
    let mut builds = Vec::new();
    for (key, policy) in inputs.policies.policies() {
        let evidence = inputs
            .evidence
            .heroes()
            .get(&key.0)
            .and_then(|hero| hero.builds.iter().find(|build| build.path_id == key.1))
            .ok_or_else(|| Error::new("Quality report has no matching build evidence"))?;
        let ability = inputs
            .abilities
            .get(policy.policy_id())
            .ok_or_else(|| Error::new("Quality report has no ability evidence"))?
            .quality_assessment();
        let replay = evaluate_policy(&inputs.evidence, policy, evidence, cases, assets)?;
        builds.push(json!({"hero_id":key.0,"path_id":key.1,"policy_id":policy.policy_id(),"snapshot_id":policy.content().snapshot_id,
            "status":combined_status([&ability, &replay].into_iter()),"reason":"Status covers support, compatibility, and route replay. It does not establish superior match outcomes.",
            "ability":ability,"replay":replay,"core_support_by_fold":evidence.core_policy.content().default_fold_matches,
            "purchase_windows":{"supported_items":evidence.items.iter().filter(|item| item.reliable_purchase_window().is_some()).count(),"items":evidence.items.len()}}));
    }
    let metadata = inputs.evidence.metadata();
    let mut report = json!({"schema_version":1,"build_evidence_id":metadata.artifact_id,"context_sha256":inputs.context_sha256,
        "replay_sha256":replay_sha256,"frozen_cutoff":inputs.cutoff,"cohort":metadata.cohort,"patch":metadata.patch,
        "client_version":metadata.client_version,"status":combined_status(builds.iter()),"builds":builds,
        "claim":"This report does not certify that a build improves match outcomes."});
    report["report_id"] = fingerprint(&report)?.into();
    Ok(report)
}

fn combined_status<'value>(values: impl Iterator<Item = &'value Value>) -> &'static str {
    let statuses = values
        .map(|value| value["status"].as_str().unwrap_or("unevaluated"))
        .collect::<Vec<_>>();
    if statuses.contains(&"fail") {
        "fail"
    } else if !statuses.is_empty() && statuses.iter().all(|status| *status == "pass") {
        "pass"
    } else {
        "unevaluated"
    }
}
