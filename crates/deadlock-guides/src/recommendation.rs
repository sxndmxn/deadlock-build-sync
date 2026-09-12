use deadlock_data::{Error, Result};
use deadlock_input::ItemGraph;
use serde_json::Value;

use crate::decision_state::DecisionState;
use crate::evidence_catalog::BuildEvidenceCatalog;
use crate::policy_model::BuildPolicy;
use crate::recommendation_guide::recommend_guide;
use crate::recommendation_policy::recommend_policy;
use crate::recommendation_types::Recommendation;
use crate::recommendation_validation::{
    observed_threats, validate_evidence_identity, validate_inventory,
};
use crate::threat::THREAT_CLASSES;

/// # Errors
/// Returns an error when the state, evidence, policy, or item mechanics are incompatible or malformed.
pub fn recommend(
    catalog: &BuildEvidenceCatalog,
    policy: &BuildPolicy,
    state: &DecisionState,
    assets: &[Value],
) -> Result<Recommendation> {
    let state = state.content();
    validate_evidence_identity(catalog, state)?;
    if policy.content().hero_id != state.hero_id {
        return Err(Error::new(
            "Decision state hero differs from the build policy",
        ));
    }
    let graph = ItemGraph::from_assets(assets)?;
    let inventory = validate_inventory(state, &graph)?;
    let unknown = state
        .threats
        .iter()
        .filter(|threat| !THREAT_CLASSES.contains(&threat.as_str()))
        .cloned()
        .collect::<Vec<_>>();
    if !unknown.is_empty() {
        return Ok(Recommendation::abstain(
            state.hero_id,
            policy.policy_id(),
            format!("Unknown threat classes: {}", unknown.join(", ")),
        ));
    }
    let threats = observed_threats(state, &graph, assets)?;
    let hero = catalog
        .heroes()
        .get(&state.hero_id)
        .ok_or_else(|| Error::new("Decision state hero is absent from build evidence"))?;
    if let Some(evidence) = hero
        .builds
        .iter()
        .find(|build| build.path_id == policy.content().path_id)
        && matches!(
            evidence.discovery.get("method").and_then(Value::as_str),
            Some("eclat_leiden_pairwise" | "eclat_leiden_beam")
        )
    {
        return recommend_guide(evidence, policy, state, assets);
    }
    recommend_policy(policy, state, &graph, inventory, &threats)
}
