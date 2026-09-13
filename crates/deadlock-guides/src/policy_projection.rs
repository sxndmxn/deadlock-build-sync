use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Error, Result, fingerprint};
use serde_json::json;

use crate::guide_category::GuideCategory;
use crate::policy_model::BuildPolicy;
use crate::policy_node::{NodeKind, PolicyNode};
use crate::policy_state::ValidationContext;
use crate::policy_validation::validate_policy;
use crate::projection_layout::project_evidence_layout;
use crate::purchase_guide::PurchaseGuide;

#[derive(Clone, Debug)]
pub struct ProjectionIdentity {
    pub hero_name: String,
    pub hero_class_name: String,
    pub client_version: u64,
    pub match_mode: String,
    pub rank_identity: String,
}

/// # Errors
/// Returns an error when the policy fails validation or its projection conflicts with the supplied item layout.
pub fn project_policy_to_guide(
    policy: &BuildPolicy,
    context: &ValidationContext,
    identity: &ProjectionIdentity,
    layout: &PurchaseGuide,
) -> Result<PurchaseGuide> {
    validate_policy(policy, context)?;
    let document = policy.content();
    let nodes = document
        .nodes
        .iter()
        .map(|node| (node.node_id.as_str(), node))
        .collect::<BTreeMap<_, _>>();
    let path = project_default_path(&nodes, &document.entry)?;
    let mut guide = project_evidence_layout(policy, layout, &path)?;
    guide.hero_id = document.hero_id;
    guide.hero_name.clone_from(&identity.hero_name);
    guide.hero_class_name.clone_from(&identity.hero_class_name);
    guide.path_id.clone_from(&document.path_id);
    guide.path_label.clone_from(&document.path_label);
    guide.snapshot_id.clone_from(&document.snapshot_id);
    guide.policy_id = policy.policy_id().into();
    guide.client_version = Some(identity.client_version);
    guide.match_mode.clone_from(&identity.match_mode);
    guide.rank_identity = guide.cohort.as_ref().map_or_else(
        || Ok(identity.rank_identity.clone()),
        |cohort| Ok::<_, Error>(cohort.rank_range()?.label()),
    )?;
    Ok(guide)
}

pub fn project_default_path<'policy>(
    nodes: &BTreeMap<&str, &'policy PolicyNode>,
    start: &str,
) -> Result<Vec<&'policy PolicyNode>> {
    let mut current = start;
    let mut seen = BTreeSet::new();
    let mut result = Vec::new();
    while seen.insert(current) {
        let node = *nodes
            .get(current)
            .ok_or_else(|| Error::new("Default path references an unknown node"))?;
        result.push(node);
        if node.kind == NodeKind::End {
            return Ok(result);
        }
        current = if matches!(node.kind, NodeKind::Choice | NodeKind::ObjectiveGate) {
            &node
                .branches
                .iter()
                .find(|branch| branch.is_default())
                .ok_or_else(|| Error::new("Choice has no default branch"))?
                .next_id
        } else {
            node.next_id
                .as_deref()
                .ok_or_else(|| Error::new("Default path does not terminate"))?
        };
    }
    Err(Error::new("Default path contains a cycle"))
}

/// # Errors
/// Returns an error when category generation or canonical JSON serialization fails.
pub fn projection_fingerprint(guide: &PurchaseGuide) -> Result<String> {
    fingerprint(&json!({
        "hero_id": guide.hero_id, "path_id": guide.path_id, "path_label": guide.path_label,
        "snapshot_id": guide.snapshot_id, "policy_id": guide.policy_id,
        "analysis_start_timestamp": guide.analysis_start_timestamp, "as_of_timestamp": guide.as_of_timestamp,
        "build": {"archetype": guide.build_archetype, "tag_ids": guide.build_tag_ids, "tag_classes": guide.build_tag_classes,
            "tag_labels": guide.build_tag_labels, "tag_catalog_sha256": guide.build_tag_catalog_sha256},
        "categories": guide.rendered_categories()?.iter().map(GuideCategory::record).collect::<Vec<_>>(),
    }))
}
