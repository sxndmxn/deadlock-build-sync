use std::collections::{BTreeMap, BTreeSet};

use deadlock_data::{Error, Result, fingerprint};
use serde_json::{Value, json};

use crate::guide_category::GuideCategory;
use crate::policy_model::BuildPolicy;
use crate::policy_node::{NodeKind, PolicyNode};
use crate::policy_state::ValidationContext;
use crate::policy_validation::validate_policy;
use crate::projection_items::{apply_sell_priorities, build_guide_item, format_branch_label};
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
    assets: &[Value],
    identity: &ProjectionIdentity,
    layout: Option<&PurchaseGuide>,
) -> Result<PurchaseGuide> {
    validate_policy(policy, context)?;
    let document = policy.content();
    let nodes = document
        .nodes
        .iter()
        .map(|node| (node.node_id.as_str(), node))
        .collect::<BTreeMap<_, _>>();
    let path = project_default_path(&nodes, &document.entry)?;
    let mut guide = if let Some(layout) = layout {
        project_evidence_layout(policy, layout, &path)?
    } else {
        let assets = assets
            .iter()
            .filter_map(|asset| asset["id"].as_u64().map(|id| (id, asset)))
            .collect();
        project_without_layout(policy, &path, &nodes, &assets)?
    };
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

fn project_without_layout(
    policy: &BuildPolicy,
    path: &[&PolicyNode],
    nodes: &BTreeMap<&str, &PolicyNode>,
    assets: &BTreeMap<u64, &Value>,
) -> Result<PurchaseGuide> {
    let mut core = path
        .iter()
        .filter(|node| node.kind == NodeKind::Purchase)
        .map(|node| build_guide_item(node, assets, policy, false))
        .collect::<Result<Vec<_>>>()?;
    if core.is_empty() {
        return Err(Error::new("Default policy path contains no purchase"));
    }
    apply_sell_priorities(&mut core, &policy.content().nodes)?;
    let ids = core.iter().map(|item| item.item_id).collect();
    let mut categories = vec![GuideCategory::new(
        "CORE — DEFAULT QUEUE".into(),
        core,
        "Minimal coherent default path. Recalculate when a conditional trigger applies.".into(),
        false,
        false,
    )?];
    categories.extend(conditional_categories(policy, nodes, assets, &ids)?);
    let tiers = (1..=4)
        .map(|tier| {
            (
                tier,
                categories
                    .iter()
                    .flat_map(|category| &category.items)
                    .filter(|item| item.tier == u64::from(tier))
                    .cloned()
                    .collect(),
            )
        })
        .collect();
    Ok(PurchaseGuide {
        tiers,
        categories,
        summary: format!(
            "{}; variant {}. Rich policy guards and uncertainty remain in the sidecar; Steam receives the declared projection.",
            policy.content().strategic_role,
            policy.content().variant
        ),
        build_archetype: "Evidence Default".into(),
        ..PurchaseGuide::default()
    })
}

fn conditional_categories(
    policy: &BuildPolicy,
    nodes: &BTreeMap<&str, &PolicyNode>,
    assets: &BTreeMap<u64, &Value>,
    default_ids: &BTreeSet<u64>,
) -> Result<Vec<GuideCategory>> {
    let mut categories = Vec::new();
    let mut seen = BTreeSet::new();
    for branch in policy
        .content()
        .nodes
        .iter()
        .flat_map(|node| &node.branches)
        .filter(|branch| !branch.is_default())
    {
        let path = project_default_path(nodes, &branch.next_id)?;
        let mut items = path
            .iter()
            .filter(|node| {
                node.kind == NodeKind::Purchase
                    && node.item_id.is_some_and(|id| !default_ids.contains(&id))
            })
            .map(|node| build_guide_item(node, assets, policy, true))
            .collect::<Result<Vec<_>>>()?;
        apply_sell_priorities(&mut items, &policy.content().nodes)?;
        let ids = items.iter().map(|item| item.item_id).collect::<Vec<_>>();
        if !ids.is_empty() && seen.insert(ids) {
            categories.push(GuideCategory::new(
                format_branch_label(branch),
                items,
                "Conditional branch; excluded from the default Queue.".into(),
                true,
                false,
            )?);
        }
    }
    Ok(categories)
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
